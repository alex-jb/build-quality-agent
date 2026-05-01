"""Reviewer — calls Claude on a git diff and returns a verdict."""
from __future__ import annotations
import json
import os
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

# Per Anthropic — Haiku 4.5 is fast + cheap, good enough for diff review.
# Override via BUILD_AGENT_MODEL env if a project wants Sonnet.
DEFAULT_MODEL = os.getenv("BUILD_AGENT_MODEL", "claude-haiku-4-5")

# Cap diff size at 50kB. Beyond this, Claude's review quality drops and
# token cost climbs. Sample the head + a hint of the tail so the model
# at least sees what shape the change takes.
MAX_DIFF_BYTES = 50_000

# Pathspecs we exclude before sending to Claude. These are high-noise,
# low-signal (lockfiles, generated types, build artifacts, binary blobs).
# Keeping them out tightens the 50kB budget for code that actually matters.
EXCLUDE_PATHSPECS = [
    ":(exclude)package-lock.json",
    ":(exclude)yarn.lock",
    ":(exclude)pnpm-lock.yaml",
    ":(exclude)bun.lock",
    ":(exclude)bun.lockb",
    ":(exclude)Cargo.lock",
    ":(exclude)poetry.lock",
    ":(exclude)Pipfile.lock",
    ":(exclude)next-env.d.ts",
    ":(exclude).next/**",
    ":(exclude)dist/**",
    ":(exclude)build/**",
    ":(exclude)out/**",
    ":(exclude)node_modules/**",
    ":(exclude)*.min.js",
    ":(exclude)*.min.css",
    ":(exclude)*.snap",
    ":(exclude)*.png",
    ":(exclude)*.jpg",
    ":(exclude)*.jpeg",
    ":(exclude)*.gif",
    ":(exclude)*.webp",
    ":(exclude)*.mp4",
    ":(exclude)*.mov",
    ":(exclude)*.woff",
    ":(exclude)*.woff2",
    ":(exclude)*.ttf",
    ":(exclude)*.otf",
    ":(exclude)*.ico",
    ":(exclude)*.pdf",
]

REVIEW_PROMPT = """You are a pre-push code reviewer. Your goal: catch bugs that would crash a Vercel/CI build BEFORE the push happens, saving build minutes.

Output EXACTLY this format (no preamble, no markdown):

VERDICT: PASS
REASON: <one sentence>

or

VERDICT: BLOCK
REASON: <one sentence — name the file:line if you can>

BLOCK only on high-confidence build/runtime breakers:
- TypeScript: import from a path that does not exist in the diff context
- TypeScript: undefined symbol used (variable / function called but not declared or imported)
- Next.js App Router: page.tsx / layout.tsx / route.ts / error.tsx / not-found.tsx without a default export
- Next.js: client-side hook (useState / useEffect / useRouter from "next/navigation") in a file without "use client"
- Next.js: server-only import (fs, child_process, server-only DB client) used in a "use client" file
- Hardcoded secrets: API keys, tokens, passwords, JWT secrets, .env values inline
- Removed auth check / RLS bypass / admin-only guard flipped to public
- console.log of sensitive data (full user object, password, token, full DB row)
- Obvious syntax errors that would fail to parse

PASS for:
- Style, formatting, naming
- Suboptimal but working code
- Missing tests, TODO comments
- Refactors that look reasonable
- Anything you are <80% confident is actually broken

When in doubt, PASS. False blocks erode trust — it's better to let through a small issue than block real work.

DIFF:
"""


@dataclass
class Review:
    """Outcome of a single review pass."""
    verdict: str            # "PASS" or "BLOCK"
    reason: str             # one-line explanation
    raw: str                # full Claude response (for logging)
    bytes_reviewed: int
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


def get_diff(diff_range: str = "@{u}..HEAD") -> str:
    """Return the git diff for the given range, with junk paths filtered out.

    Default range = "everything between upstream and HEAD" — i.e. the
    commits this push will deliver. Falls back to HEAD~1..HEAD if no
    upstream is configured (e.g. first push of a new branch).

    Lockfiles, generated types, build output, and binary assets are
    excluded so the 50kB budget gets spent on actual source changes.
    """
    cmd_with_excludes = ["git", "diff", diff_range, "--"] + EXCLUDE_PATHSPECS
    try:
        result = subprocess.run(
            cmd_with_excludes, capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return result.stdout
        fallback = ["git", "diff", "HEAD~1..HEAD", "--"] + EXCLUDE_PATHSPECS
        result = subprocess.run(
            fallback, capture_output=True, text=True, timeout=15,
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""


def diff_range_from_pre_push_stdin(stdin_text: str) -> str | None:
    """Parse git's pre-push hook stdin and return the precise diff range.

    git passes one line per ref being pushed:
        <local_ref> <local_oid> <remote_ref> <remote_oid>

    Returns the range to diff, or None if there's nothing reviewable
    (deletions, empty stdin). For a brand-new branch (remote_oid is all
    zeros), tries `merge-base origin/HEAD..local_oid` so we review only
    the new commits, not the entire branch history.
    """
    if not stdin_text or not stdin_text.strip():
        return None

    ZERO = "0" * 40
    for line in stdin_text.strip().splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        _local_ref, local_oid, _remote_ref, remote_oid = parts

        if local_oid == ZERO:
            # branch deletion — nothing to review
            continue

        if remote_oid == ZERO:
            # new branch — find the merge base with a likely default branch
            for base in ("origin/HEAD", "origin/main", "origin/master"):
                try:
                    r = subprocess.run(
                        ["git", "merge-base", base, local_oid],
                        capture_output=True, text=True, timeout=5,
                    )
                    if r.returncode == 0 and r.stdout.strip():
                        return f"{r.stdout.strip()}..{local_oid}"
                except Exception:
                    pass
            return f"{local_oid}~1..{local_oid}"

        return f"{remote_oid}..{local_oid}"

    return None


def review(diff: str, model: str = DEFAULT_MODEL) -> Review:
    """Run Claude over a diff. Returns Review with PASS/BLOCK + reason.

    Empty diff = automatic PASS (nothing to review).
    No ANTHROPIC_API_KEY = automatic PASS with a warning (graceful
    degradation; the agent should never block a push because of its own
    config gap).
    """
    if not diff or not diff.strip():
        return Review("PASS", "no diff to review", "", 0, model=model)

    if not os.getenv("ANTHROPIC_API_KEY"):
        return Review("PASS",
                      "skipped (ANTHROPIC_API_KEY not set)",
                      "", len(diff), model=model)

    sampled = diff[:MAX_DIFF_BYTES]
    if len(diff) > MAX_DIFF_BYTES:
        sampled += f"\n\n[... diff truncated at {MAX_DIFF_BYTES} bytes; "
        sampled += f"original {len(diff)} bytes ...]"

    # v0.4: route LLM call through solo-founder-os AnthropicClient. Token
    # usage is auto-logged (we still write the BQA-shaped row below for
    # the verdict + bytes fields cost-audit/funnel don't track).
    from solo_founder_os.anthropic_client import AnthropicClient
    client = AnthropicClient(usage_log_path=None)  # we self-log below for richer schema
    resp, err = client.messages_create(
        model=model,
        max_tokens=400,
        messages=[{"role": "user", "content": REVIEW_PROMPT + sampled}],
    )
    if err is not None:
        return Review("PASS", f"agent error (degraded): {err}",
                      "", len(diff), model=model)

    text = AnthropicClient.extract_text(resp)
    in_tok = getattr(resp.usage, "input_tokens", 0) if hasattr(resp, "usage") else 0
    out_tok = getattr(resp.usage, "output_tokens", 0) if hasattr(resp, "usage") else 0

    m = re.search(r"VERDICT\s*:\s*(PASS|BLOCK)", text, re.IGNORECASE)
    verdict = m.group(1).upper() if m else "PASS"
    rm = re.search(r"REASON\s*:\s*(.+)", text, re.IGNORECASE)
    reason = rm.group(1).strip() if rm else (text[:200] if text else "no parseable verdict — failing open")

    r = Review(verdict, reason, text, len(diff),
               input_tokens=in_tok, output_tokens=out_tok, model=model)
    _log_usage(r)

    # Reflexion log: BLOCK verdicts mean the agent stopped a sloppy push.
    # Logging this teaches future reviews what kinds of issues we keep
    # making. Best-effort — wrapped in a try/import so older
    # solo-founder-os versions don't break this hot path.
    if verdict == "BLOCK":
        try:
            from solo_founder_os import log_outcome
            log_outcome(".build-quality-agent", task="review_diff",
                        outcome="FAILED",
                        signal=f"BLOCK: {reason[:200]}")
        except Exception:
            pass
    else:
        # PASS verdicts feed the L3 skill library — what does a "good
        # review of a clean diff" look like across many runs? Record
        # only structural signals (length, model), not the diff itself
        # (it may contain secrets in transit even if not committed).
        try:
            from solo_founder_os import record_example
            record_example(
                "review-diff-pass",
                inputs={"diff_bytes": len(diff), "model": model},
                output=f"VERDICT: PASS\nREASON: {reason[:200]}",
                note=f"Claude PASS verdict, {in_tok}+{out_tok} tokens",
            )
        except Exception:
            pass

    return r


def _usage_log_path() -> pathlib.Path:
    """Resolve the usage log location. Honors BUILD_AGENT_USAGE_LOG so
    tests + CI can redirect to a tmp path without touching the real log.
    """
    override = os.getenv("BUILD_AGENT_USAGE_LOG")
    if override:
        return pathlib.Path(override)
    return pathlib.Path.home() / ".build-quality-agent" / "usage.jsonl"


def _log_usage(r: Review) -> None:
    """Append a row to the usage log. Best-effort — silently drops on any
    failure (we don't want logging to break a hook).
    """
    try:
        path = _usage_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "model": r.model,
                "verdict": r.verdict,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "bytes": r.bytes_reviewed,
            }) + "\n")
    except Exception:
        pass


def usage_report() -> str:
    """Aggregate ~/.build-quality-agent/usage.jsonl into a readable summary.

    Haiku 4.5 pricing as of 2026-04: $1/MTok input, $5/MTok output.
    Sonnet 4.6: $3/MTok input, $15/MTok output. Costs are estimates.
    """
    log = _usage_log_path()
    if not log.exists():
        return "No usage logged yet. Push something first."

    PRICES = {
        "claude-haiku-4-5":  (1.0,  5.0),
        "claude-sonnet-4-6": (3.0, 15.0),
    }

    total = {"runs": 0, "pass": 0, "block": 0, "in": 0, "out": 0, "cost": 0.0}
    by_model: dict[str, dict] = {}

    with log.open() as f:
        for line in f:
            try:
                row = json.loads(line)
            except Exception:
                continue
            total["runs"] += 1
            total["pass"] += int(row.get("verdict") == "PASS")
            total["block"] += int(row.get("verdict") == "BLOCK")
            total["in"] += row.get("input_tokens", 0)
            total["out"] += row.get("output_tokens", 0)
            model = row.get("model", "unknown")
            in_p, out_p = PRICES.get(model, (1.0, 5.0))
            cost = (row.get("input_tokens", 0) * in_p
                    + row.get("output_tokens", 0) * out_p) / 1_000_000
            total["cost"] += cost
            m = by_model.setdefault(model, {"runs": 0, "in": 0, "out": 0, "cost": 0.0})
            m["runs"] += 1
            m["in"] += row.get("input_tokens", 0)
            m["out"] += row.get("output_tokens", 0)
            m["cost"] += cost

    out = []
    out.append("build-quality-agent — usage report")
    out.append(f"  {total['runs']} runs · {total['pass']} pass · {total['block']} block")
    out.append(f"  {total['in']:,} input tokens · {total['out']:,} output tokens")
    out.append(f"  ~${total['cost']:.4f} total")
    out.append("")
    for model, m in by_model.items():
        out.append(f"  {model}: {m['runs']} runs · "
                   f"{m['in']:,} in / {m['out']:,} out · ~${m['cost']:.4f}")
    return "\n".join(out)


def format_output(r: Review, *, color: bool = True) -> str:
    """Render a Review for the terminal."""
    if not color or not sys.stderr.isatty():
        prefix = "✓" if r.verdict == "PASS" else "✗"
        return f"{prefix} build-quality-agent: {r.verdict} — {r.reason}"
    green, red, dim, end = "\033[32m", "\033[31m", "\033[2m", "\033[0m"
    icon = f"{green}✓{end}" if r.verdict == "PASS" else f"{red}✗{end}"
    head = f"{icon} build-quality-agent: {r.verdict}"
    tail = f"{dim}{r.reason}{end}"
    return f"{head} — {tail}"
