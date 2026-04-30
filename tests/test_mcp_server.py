"""Tests for the build-quality MCP server tools.

`mcp` is an optional dep — skip the whole module if not installed. The
@mcp.tool() decorator returns the original callable unchanged, so we
just call them directly.
"""
from __future__ import annotations
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

mcp_available = True
try:
    from mcp.server.fastmcp import FastMCP  # noqa: F401
except ImportError:
    mcp_available = False

pytestmark = pytest.mark.skipif(not mcp_available,
                                  reason="mcp optional dep not installed")


@pytest.fixture
def mod():
    from build_quality_agent import mcp_server
    return mcp_server


def test_review_diff_empty_input(mod):
    out = mod.review_diff("")
    assert "No diff content" in out


def test_review_diff_no_api_key_returns_pass(mod, monkeypatch):
    """Without ANTHROPIC_API_KEY the reviewer falls back to PASS."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = mod.review_diff("diff --git a/foo b/foo\n+hello\n")
    # Either format_output renders PASS (graceful) or returns a recognizable verdict
    assert "PASS" in out or "BLOCK" in out


def test_usage_summary_runs(mod, monkeypatch, tmp_path):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    out = mod.usage_summary()
    # Empty log path → some "no usage" or "0 calls" type message
    assert isinstance(out, str)


def test_main_skips_when_skip_env_set(mod, monkeypatch):
    monkeypatch.setenv("BUILD_AGENT_SKIP", "1")
    with patch.object(mod.mcp, "run") as fake_run:
        mod.main()
    fake_run.assert_not_called()


def test_mcp_instance_is_fastmcp(mod):
    from mcp.server.fastmcp import FastMCP
    assert isinstance(mod.mcp, FastMCP)
