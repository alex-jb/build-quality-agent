"""Reviewer — calls Claude on a git diff and returns a verdict."""
from __future__ import annotations
import os
import re
import subprocess
import sys
from dataclasses import dataclass

# Per Anthropic — Haiku 4.5 is fast + cheap, good enough for diff review.
# Override via BUILD_AGENT_MODEL env if a project wants Sonnet.
DEFAULT_MODEL = os.getenv("BUILD_AGENT_MODEL", "claude-haiku-4-5")

# Cap diff size at 50kB. Beyond this, Claude's review quality drops and
# token cost climbs. Sample the head + a hint of the tail so the model
# at least sees what shape the change takes.
MAX_DIFF_BYTES = 50_000

REVIEW_PROMPT = """You are a senior engineer reviewing a git diff before it gets pushed to production.

Your job: catch issues that would break a build, ship a security risk, or land an obvious bug. NOT to do code style nitpicks.

Return EXACTLY this format (no preamble):

VERDICT: <PASS or BLOCK>
REASON: <one line explaining why>

Use BLOCK only for clear failures:
- Type errors visible in the diff
- Removed required imports / undefined symbols
- Hardcoded secrets / API keys
- Reverted critical security checks (auth, RLS, rate limit)
- Obvious null-deref / unhandled error paths
- console.log left in production code (warn but don't block unless egregious)

Use PASS for everything else, including: style preferences, minor naming, comments, config tweaks, doc-only changes, refactors that look reasonable.

When in doubt, PASS. The cost of blocking a good push is higher than letting through a small issue.

DIFF:
"""


@dataclass
class Review:
    """Outcome of a single review pass."""
    verdict: str       # "PASS" or "BLOCK"
    reason: str        # one-line explanation
    raw: str           # full Claude response (for logging)
    bytes_reviewed: int


def get_diff(diff_range: str = "@{u}..HEAD") -> str:
    """Return the git diff for the given range. Empty string if no commits.

    Default range = "everything between upstream and HEAD" — i.e. the
    commits this push will deliver. Falls back to HEAD~1..HEAD if no
    upstream is configured (e.g. first push of a new branch).
    """
    try:
        result = subprocess.run(
            ["git", "diff", diff_range],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return result.stdout
        # Fall back to HEAD~1..HEAD when @{u} is unset
        result = subprocess.run(
            ["git", "diff", "HEAD~1..HEAD"],
            capture_output=True, text=True, timeout=15,
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""


def review(diff: str, model: str = DEFAULT_MODEL) -> Review:
    """Run Claude over a diff. Returns Review with PASS/BLOCK + reason.

    Empty diff = automatic PASS (nothing to review).
    No ANTHROPIC_API_KEY = automatic PASS with a warning (graceful
    degradation; the agent should never block a push because of its own
    config gap).
    """
    if not diff or not diff.strip():
        return Review("PASS", "no diff to review", "", 0)

    if not os.getenv("ANTHROPIC_API_KEY"):
        return Review("PASS",
                      "skipped (ANTHROPIC_API_KEY not set)", "", len(diff))

    sampled = diff[:MAX_DIFF_BYTES]
    if len(diff) > MAX_DIFF_BYTES:
        sampled += f"\n\n[... diff truncated at {MAX_DIFF_BYTES} bytes; "
        sampled += f"original {len(diff)} bytes ...]"

    try:
        from anthropic import Anthropic
        client = Anthropic()
        resp = client.messages.create(
            model=model,
            max_tokens=400,
            messages=[{"role": "user", "content": REVIEW_PROMPT + sampled}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception as e:
        # Network / auth / rate-limit errors should not block a push.
        # Better to let an unverified push through than block legitimate
        # work. Surface the error so the user knows the agent is degraded.
        return Review("PASS", f"agent error (degraded): {e}", "", len(diff))

    # Parse "VERDICT: ..." line. Tolerant to whitespace + casing.
    m = re.search(r"VERDICT\s*:\s*(PASS|BLOCK)", text, re.IGNORECASE)
    verdict = m.group(1).upper() if m else "PASS"
    rm = re.search(r"REASON\s*:\s*(.+)", text, re.IGNORECASE)
    reason = rm.group(1).strip() if rm else text[:200]
    return Review(verdict, reason, text, len(diff))


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
