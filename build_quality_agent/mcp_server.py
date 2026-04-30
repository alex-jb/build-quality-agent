"""MCP (Model Context Protocol) server — expose BQA review tools to
Claude Desktop / Cursor / Zed / Claude Code so you can review a diff
inline without leaving the AI assistant.

Tools:
  - review_diff(diff)       Run a Claude review on a git diff string
  - review_range(range)     Review a git revision range from the current repo
  - usage_summary()         Token + $ totals from local usage log

Install:
    pip install build-quality-agent[mcp]

Wire to Claude Desktop:

    {
      "mcpServers": {
        "build-quality": {
          "command": "build-quality-mcp",
          "env": { "ANTHROPIC_API_KEY": "..." }
        }
      }
    }
"""
from __future__ import annotations
import os
import sys

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:
    print("build-quality-mcp requires the `mcp` package. "
          "Install with: pip install 'build-quality-agent[mcp]'",
          file=sys.stderr)
    raise SystemExit(1) from e

from .reviewer import (
    DEFAULT_MODEL,
    format_output,
    get_diff,
    review,
    usage_report,
)


mcp = FastMCP("build-quality")


@mcp.tool()
def review_diff(diff: str, model: str = DEFAULT_MODEL) -> str:
    """Run a Claude review on a unified git diff string.

    Returns a markdown verdict (PASS / BLOCK + one-line reason).

    Args:
        diff: unified git diff, e.g. output of `git diff origin/main..HEAD`
        model: claude model id (default: claude-haiku-4-5)
    """
    if not diff.strip():
        return "No diff content to review."
    r = review(diff, model=model)
    return format_output(r, color=False)


@mcp.tool()
def review_range(diff_range: str = "@{u}..HEAD",
                  model: str = DEFAULT_MODEL) -> str:
    """Review a git revision range in the current working directory.

    Args:
        diff_range: e.g. "main..HEAD", "@{u}..HEAD", "abc123..def456"
        model: claude model id (default: claude-haiku-4-5)
    """
    diff = get_diff(diff_range)
    if not diff.strip():
        return f"No diff for range {diff_range!r} (empty)."
    r = review(diff, model=model)
    return format_output(r, color=False)


@mcp.tool()
def usage_summary() -> str:
    """Token usage + estimated $ totals from this agent's local usage log
    (~/.build-quality-agent/usage.jsonl).
    """
    return usage_report()


def main() -> None:
    """Console-script entry point. Runs the MCP server over stdio."""
    if os.getenv("BUILD_AGENT_SKIP") == "1":
        return
    mcp.run()


if __name__ == "__main__":
    main()
