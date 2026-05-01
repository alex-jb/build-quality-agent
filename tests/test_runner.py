"""Tests for runner — build detection + execution."""
from __future__ import annotations
import json

import pytest

from build_quality_agent.runner import (
    BuildResult, detect_build, format_for_review, run_build,
)


def test_detect_build_returns_none_when_no_manifest(tmp_path):
    assert detect_build(tmp_path) is None


def test_detect_build_finds_npm_when_package_json_has_build_script(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "scripts": {"build": "tsc"},
    }))
    cmd = detect_build(tmp_path)
    # Should at least pick *some* JS runner that's installed
    assert cmd is not None
    assert any(c in (cmd[0] or "") for c in ("npm", "pnpm", "yarn", "bun"))


def test_detect_build_skips_when_package_json_has_no_build_script(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "scripts": {"test": "vitest"},
    }))
    assert detect_build(tmp_path) is None


def test_detect_build_finds_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\nversion='0.1'\n")
    cmd = detect_build(tmp_path)
    assert cmd is not None
    assert "python" in cmd[0] or "python3" in cmd[0]


def test_detect_build_finds_cargo(tmp_path):
    import shutil
    if not shutil.which("cargo"):
        pytest.skip("cargo not installed in this CI runner")
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'x'\nversion = '0.1.0'\n")
    cmd = detect_build(tmp_path)
    assert cmd is not None
    assert cmd[0] == "cargo"


def test_run_build_returns_skipped_when_no_manifest(tmp_path):
    r = run_build(tmp_path)
    assert isinstance(r, BuildResult)
    assert r.passed is False
    assert r.skipped_reason and "no build detected" in r.skipped_reason


def test_run_build_handles_command_not_found(tmp_path):
    r = run_build(tmp_path, command=["nonexistent-binary-xyz", "--help"])
    assert r.passed is False
    assert r.skipped_reason and "command not found" in r.skipped_reason


def test_run_build_captures_failure_exit_code(tmp_path):
    # `false` always exits 1 — perfect for testing the failure path
    r = run_build(tmp_path, command=["false"])
    assert r.passed is False
    assert r.exit_code == 1
    assert r.skipped_reason is None  # not skipped — actually ran


def test_run_build_captures_success(tmp_path):
    # `true` always exits 0
    r = run_build(tmp_path, command=["true"])
    assert r.passed is True
    assert r.exit_code == 0


def test_format_for_review_skipped(tmp_path):
    r = BuildResult(passed=False, command=[], duration_s=0,
                       skipped_reason="no manifest")
    out = format_for_review(r)
    assert "BUILD SKIPPED" in out
    assert "no manifest" in out


def test_format_for_review_passed():
    r = BuildResult(passed=True, command=["true"], duration_s=0.1, exit_code=0)
    out = format_for_review(r)
    assert "PASSED" in out


def test_format_for_review_failed_truncates_long_output():
    big = "X" * 10_000
    r = BuildResult(passed=False, command=["false"], duration_s=0.5,
                       exit_code=1, stderr=big)
    out = format_for_review(r)
    assert "FAILED" in out
    assert "(truncated)" in out
    # Should not contain all 10k X's — truncated to last 4k
    assert out.count("X") <= 4_500
