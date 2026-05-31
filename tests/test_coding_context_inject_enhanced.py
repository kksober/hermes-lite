"""Tests for per-turn context injection and framework detection."""
from __future__ import annotations

import subprocess


def test_detect_frameworks_python(tmp_path) -> None:
    from hermes_lite.coding.context_inject import detect_frameworks

    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'")
    result = detect_frameworks(tmp_path)
    assert result["language"] == "Python"
    assert "pyproject.toml" in result["files"]


def test_detect_frameworks_node(tmp_path) -> None:
    from hermes_lite.coding.context_inject import detect_frameworks

    (tmp_path / "package.json").write_text('{"name": "test"}')
    result = detect_frameworks(tmp_path)
    assert result["language"] == "Node.js / TypeScript"


def test_detect_frameworks_multi(tmp_path) -> None:
    from hermes_lite.coding.context_inject import detect_frameworks

    (tmp_path / "pyproject.toml").write_text("[project]")
    (tmp_path / "Dockerfile").write_text("FROM python:3.11")
    result = detect_frameworks(tmp_path)
    assert result["language"] == "Python"
    assert len(result["files"]) == 2


def test_detect_frameworks_unknown(tmp_path) -> None:
    from hermes_lite.coding.context_inject import detect_frameworks

    result = detect_frameworks(tmp_path)
    assert result["language"] == "unknown"


def test_per_turn_context_returns_nonempty_in_git_repo(tmp_path) -> None:
    from hermes_lite.coding.context_inject import per_turn_context

    # tmp_path is inside the project git repo, so per_turn_context
    # should produce a meaningful context snippet.
    result = per_turn_context(tmp_path)
    assert "branch:" in result
    assert "</workspace_state>" in result


def test_per_turn_context_includes_branch_when_git(tmp_path) -> None:
    from hermes_lite.coding.context_inject import per_turn_context

    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], capture_output=True)
    result = per_turn_context(tmp_path)
    assert "branch:" in result
    assert "</workspace_state>" in result
