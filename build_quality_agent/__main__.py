"""CLI entry — used both for manual `python -m build_quality_agent`
and as the actual git pre-push hook target.

Pre-push hook contract: stdin receives lines like
    <local_ref> <local_oid> <remote_ref> <remote_oid>

We read them when present so the diff range matches exactly what's being
pushed (handles new branches without upstream, multiple ref pushes, etc).
For manual runs (no stdin), we fall back to `--diff-range` arg or @{u}..HEAD.

Bypass: BUILD_AGENT_SKIP=1 git push
(--no-verify also works but is silent — the env var is louder)
"""
from __future__ import annotations
import argparse
import os
import select
import sys

from .reviewer import (
    diff_range_from_pre_push_stdin,
    format_output,
    get_diff,
    review,
    usage_report,
)


def _read_stdin_nonblocking() -> str:
    """Return stdin text if any is available, else "". Doesn't hang if
    stdin is a terminal (manual run) — only reads when piped from git.
    """
    if sys.stdin.isatty():
        return ""
    try:
        ready, _, _ = select.select([sys.stdin], [], [], 0.1)
        if ready:
            return sys.stdin.read()
    except Exception:
        pass
    return ""


def main(argv: list[str] | None = None) -> int:
    if os.getenv("BUILD_AGENT_SKIP") == "1":
        print("⏭  build-quality-agent skipped (BUILD_AGENT_SKIP=1)",
              file=sys.stderr)
        return 0

    p = argparse.ArgumentParser(
        prog="build-quality-agent",
        description="Claude-powered git pre-push diff reviewer.",
    )
    p.add_argument("--diff-range", default=None,
                   help="git revision range (default: read from git stdin, "
                        "fall back to @{u}..HEAD)")
    p.add_argument("--model",
                   default=os.getenv("BUILD_AGENT_MODEL", "claude-haiku-4-5"))
    p.add_argument("--no-block", action="store_true",
                   help="Always exit 0; print verdict but don't block push")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress output unless BLOCK")
    p.add_argument("--usage", action="store_true",
                   help="Print token usage + cost report and exit")
    args = p.parse_args(argv)

    if args.usage:
        print(usage_report())
        return 0

    diff_range = args.diff_range
    if diff_range is None:
        stdin_text = _read_stdin_nonblocking()
        diff_range = diff_range_from_pre_push_stdin(stdin_text) or "@{u}..HEAD"

    diff = get_diff(diff_range)
    r = review(diff, model=args.model)

    if not args.quiet or r.verdict == "BLOCK":
        print(format_output(r), file=sys.stderr)

    if r.verdict == "BLOCK" and not args.no_block:
        print("", file=sys.stderr)
        print("To push anyway, prefix the command with BUILD_AGENT_SKIP=1.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
