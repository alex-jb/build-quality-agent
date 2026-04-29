"""CLI entry — used both for manual `python -m build_quality_agent`
and as the actual git pre-push hook target.

Pre-push hook contract: stdin receives lines like
   <local-ref> <local-sha> <remote-ref> <remote-sha>
We don't currently parse them — we just diff @{u}..HEAD which covers
the same range for the common 'push current branch' case.

Bypass: BUILD_AGENT_SKIP=1 git push --no-verify-can't-bypass-this
(use the env var; --no-verify still works but is louder)
"""
from __future__ import annotations
import argparse
import os
import sys
from .reviewer import get_diff, review, format_output


def main(argv: list[str] | None = None) -> int:
    if os.getenv("BUILD_AGENT_SKIP") == "1":
        print("⏭  build-quality-agent skipped (BUILD_AGENT_SKIP=1)",
              file=sys.stderr)
        return 0

    p = argparse.ArgumentParser(
        prog="build-quality-agent",
        description="Claude-powered git pre-push diff reviewer.",
    )
    p.add_argument("--diff-range", default="@{u}..HEAD",
                   help="git revision range (default: @{u}..HEAD)")
    p.add_argument("--model",
                   default=os.getenv("BUILD_AGENT_MODEL", "claude-haiku-4-5"))
    p.add_argument("--no-block", action="store_true",
                   help="Always exit 0; print verdict but don't block push")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress output unless BLOCK")
    args = p.parse_args(argv)

    diff = get_diff(args.diff_range)
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
