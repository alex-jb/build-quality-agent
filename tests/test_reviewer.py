"""Tests for build_quality_agent.reviewer.

Mocks the anthropic.Anthropic client so we can run offline + deterministic.
"""
from __future__ import annotations
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Make the package importable when running tests directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from build_quality_agent.reviewer import (
    diff_range_from_pre_push_stdin,
    review,
)


@pytest.fixture(autouse=True)
def _redirect_usage_log(tmp_path, monkeypatch):
    """Send usage log writes to a tmp file so tests never pollute
    ~/.build-quality-agent/usage.jsonl on the dev machine."""
    monkeypatch.setenv("BUILD_AGENT_USAGE_LOG", str(tmp_path / "usage.jsonl"))


def _fake_anthropic(text: str, in_tok: int = 100, out_tok: int = 20):
    """Build a MagicMock that mimics the anthropic.Anthropic client."""
    block = MagicMock()
    block.text = text
    block.type = "text"
    resp = MagicMock()
    resp.content = [block]
    resp.usage.input_tokens = in_tok
    resp.usage.output_tokens = out_tok
    client = MagicMock()
    client.messages.create.return_value = resp
    return client


def test_empty_diff_passes():
    r = review("")
    assert r.verdict == "PASS"
    assert "no diff" in r.reason.lower()


def test_no_api_key_passes(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = review("diff --git a/foo b/foo\n+changed")
    assert r.verdict == "PASS"
    assert "key" in r.reason.lower()


def test_claude_returns_pass(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake = _fake_anthropic("VERDICT: PASS\nREASON: looks fine")
    with patch("anthropic.Anthropic", return_value=fake):
        r = review("diff --git a/foo b/foo\n+ok")
    assert r.verdict == "PASS"
    assert r.reason == "looks fine"
    assert r.input_tokens == 100
    assert r.output_tokens == 20


def test_claude_returns_block(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake = _fake_anthropic(
        "VERDICT: BLOCK\nREASON: missing import in foo.ts:42")
    with patch("anthropic.Anthropic", return_value=fake):
        r = review("diff --git a/foo.ts b/foo.ts\n-import x\n+x()")
    assert r.verdict == "BLOCK"
    assert "foo.ts:42" in r.reason


def test_claude_garbage_response_fails_open(monkeypatch):
    """No parseable VERDICT line → default to PASS, never block."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake = _fake_anthropic("hello world this is not a verdict format")
    with patch("anthropic.Anthropic", return_value=fake):
        r = review("diff --git a/foo b/foo\n+ok")
    assert r.verdict == "PASS"


def test_claude_exception_fails_open(monkeypatch):
    """Network/auth failure → graceful PASS with degraded reason."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake = MagicMock()
    fake.messages.create.side_effect = Exception("network down")
    with patch("anthropic.Anthropic", return_value=fake):
        r = review("diff --git a/foo b/foo\n+ok")
    assert r.verdict == "PASS"
    assert "degraded" in r.reason.lower()
    assert "network down" in r.reason


def test_diff_range_stdin_empty_returns_none():
    assert diff_range_from_pre_push_stdin("") is None
    assert diff_range_from_pre_push_stdin("   ") is None


def test_diff_range_stdin_normal_push():
    line = "refs/heads/main abc123def456 refs/heads/main 0000000aaa111"
    # remote_oid is non-zero → use remote..local range
    r = diff_range_from_pre_push_stdin(line)
    assert r == "0000000aaa111..abc123def456"


def test_diff_range_stdin_branch_deletion_skipped():
    zero = "0" * 40
    line = f"(delete) {zero} refs/heads/feature abc123"
    assert diff_range_from_pre_push_stdin(line) is None


def test_diff_range_stdin_malformed_lines_ignored():
    assert diff_range_from_pre_push_stdin("only two parts") is None


def test_usage_log_written_on_real_call(monkeypatch, tmp_path):
    """A successful Claude call should write a row to the usage log."""
    log_path = tmp_path / "usage.jsonl"
    monkeypatch.setenv("BUILD_AGENT_USAGE_LOG", str(log_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake = _fake_anthropic("VERDICT: PASS\nREASON: ok",
                           in_tok=1234, out_tok=56)
    with patch("anthropic.Anthropic", return_value=fake):
        review("diff --git a/x b/x\n+y")
    assert log_path.exists()
    import json
    row = json.loads(log_path.read_text().strip())
    assert row["verdict"] == "PASS"
    assert row["input_tokens"] == 1234
    assert row["output_tokens"] == 56


def test_usage_log_skipped_when_no_real_call(monkeypatch, tmp_path):
    """Empty diff and missing key paths should NOT write to the log —
    only real Claude calls produce billable usage."""
    log_path = tmp_path / "usage.jsonl"
    monkeypatch.setenv("BUILD_AGENT_USAGE_LOG", str(log_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    review("diff --git a/x b/x\n+y")
    review("")
    assert not log_path.exists()
