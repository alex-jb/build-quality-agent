"""Build runner — optionally execute the project's build before pushing.

Why? The diff reviewer catches "obvious" bugs (typos, missing imports). The
local build catches real type errors that would otherwise burn 5-6 minutes
of remote CI. Combined, they cover the failure modes from the $131.92
April Vercel bill almost completely.

Detection precedence (first match wins):
    1. If package.json has a `build` script → run with bun → pnpm → yarn → npm
       (whichever lockfile is present)
    2. pyproject.toml with `[project]` block → `python -m build`
    3. Cargo.toml → `cargo check --quiet`
    4. go.mod → `go build ./...`

Returns BuildResult(passed, command, duration_s, stdout, stderr, exit_code).

If the build fails, the caller (reviewer.py) sends the tail of stderr/stdout
to Claude alongside the diff for a unified review. If the build passes,
we still run the diff review — catching things the build can't (like
removing a feature flag's fallback path).

Cap: 4-minute build timeout. Most local builds for indie projects are
30-90s; if you have a 4+ minute local build you have other problems.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_TIMEOUT_S = 240  # 4 minutes — a hard ceiling.


@dataclass
class BuildResult:
    """Outcome of a local build attempt."""
    passed: bool
    command: list[str]
    duration_s: float
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    skipped_reason: Optional[str] = None  # set when no build was found


def _exists(p: Path) -> bool:
    return p.exists()


def _which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def detect_build(repo_root: Path) -> Optional[list[str]]:
    """Return the build command for this repo, or None if none detected.

    Tries lockfile → runner mapping for JS, then language-specific builds.
    """
    pkg = repo_root / "package.json"
    if _exists(pkg):
        # Read scripts.build to confirm a "build" script exists
        try:
            import json
            data = json.loads(pkg.read_text())
            if "build" in (data.get("scripts") or {}):
                if _exists(repo_root / "bun.lock") or _exists(repo_root / "bun.lockb"):
                    if _which("bun"):
                        return ["bun", "run", "build"]
                if _exists(repo_root / "pnpm-lock.yaml"):
                    if _which("pnpm"):
                        return ["pnpm", "build"]
                if _exists(repo_root / "yarn.lock"):
                    if _which("yarn"):
                        return ["yarn", "build"]
                if _which("npm"):
                    return ["npm", "run", "build"]
        except Exception:
            pass

    if _exists(repo_root / "pyproject.toml"):
        if _which("python") or _which("python3"):
            py = _which("python3") or _which("python") or "python3"
            return [py, "-m", "build"]

    if _exists(repo_root / "Cargo.toml"):
        if _which("cargo"):
            return ["cargo", "check", "--quiet"]

    if _exists(repo_root / "go.mod"):
        if _which("go"):
            return ["go", "build", "./..."]

    return None


def run_build(repo_root: Path, *,
                timeout_s: int = DEFAULT_TIMEOUT_S,
                command: Optional[list[str]] = None) -> BuildResult:
    """Run the detected build command, return BuildResult.

    Never raises — timeouts and missing tools become BuildResult fields so
    the caller can flow control on .passed / .skipped_reason.
    """
    cmd = command or detect_build(repo_root)
    if cmd is None:
        return BuildResult(
            passed=False, command=[], duration_s=0.0,
            skipped_reason="no build detected (no package.json/build, "
                              "pyproject.toml, Cargo.toml, or go.mod)",
        )

    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=str(repo_root), timeout=timeout_s,
            capture_output=True, text=True,
            env={**os.environ, "CI": "1"},  # mimic CI for stricter behavior
        )
    except subprocess.TimeoutExpired as e:
        return BuildResult(
            passed=False, command=cmd, duration_s=timeout_s,
            stdout=(e.stdout or b"").decode("utf-8", errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""),
            stderr=(e.stderr or b"").decode("utf-8", errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or ""),
            exit_code=124,
            skipped_reason=f"build timed out after {timeout_s}s",
        )
    except FileNotFoundError as e:
        return BuildResult(
            passed=False, command=cmd, duration_s=0.0, exit_code=127,
            skipped_reason=f"command not found: {e.filename}",
        )

    duration = time.monotonic() - started
    return BuildResult(
        passed=(proc.returncode == 0),
        command=cmd,
        duration_s=round(duration, 2),
        stdout=proc.stdout[-10_000:],  # cap retained output at 10kB tail
        stderr=proc.stderr[-10_000:],
        exit_code=proc.returncode,
    )


def format_for_review(result: BuildResult) -> str:
    """Render a BuildResult as a string snippet to append to the diff prompt."""
    if result.skipped_reason:
        return f"\n[BUILD SKIPPED: {result.skipped_reason}]\n"
    head = f"\n[BUILD: {' '.join(result.command)}  →  exit {result.exit_code}  ({result.duration_s}s)]\n"
    if result.passed:
        return head + "[PASSED]\n"
    body = (result.stderr or result.stdout or "").strip()
    # Tail-truncate: only the last 4kB of build log goes to Claude
    if len(body) > 4_000:
        body = "...(truncated)...\n" + body[-4_000:]
    return head + "FAILED — last lines of output:\n" + body + "\n"
