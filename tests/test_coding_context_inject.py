"""Tests for auto-context injection: rules.md and workspace snapshot."""
from __future__ import annotations

import subprocess
from textwrap import dedent


# ---------------------------------------------------------------------------
# rules.md discovery
# ---------------------------------------------------------------------------

def test_discover_rules_finds_project_rules(tmp_path) -> None:
    from hermes_lite.coding.context_inject import discover_rules

    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    (hermes_dir / "rules.md").write_text("# Project Rules\n- Use pytest.")

    result = discover_rules(tmp_path)
    assert result["found"] is True
    assert "# Project Rules" in result["content"]


def test_discover_rules_returns_empty_when_missing(tmp_path) -> None:
    from hermes_lite.coding.context_inject import discover_rules

    result = discover_rules(tmp_path)
    assert result["found"] is False
    assert result["content"] == ""


def test_discover_rules_truncates_long_rules(tmp_path) -> None:
    from hermes_lite.coding.context_inject import discover_rules

    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    long_content = "A" * 5000
    (hermes_dir / "rules.md").write_text(long_content)

    result = discover_rules(tmp_path)
    assert result["found"] is True
    assert len(result["content"]) <= 3000  # 默认截断


def test_discover_rules_reads_nearby_markdown(tmp_path) -> None:
    """Also discover CLAUDE.md or AGENTS.md as fallback."""
    from hermes_lite.coding.context_inject import discover_rules

    (tmp_path / "CLAUDE.md").write_text("Rules from CLAUDE.md")

    result = discover_rules(tmp_path)
    assert result["found"] is True
    assert "CLAUDE.md" in result.get("source", "")


# ---------------------------------------------------------------------------
# workspace context snapshot
# ---------------------------------------------------------------------------

def test_workspace_snapshot_has_git_info(tmp_path) -> None:
    import shutil
    if shutil.which("git") is None:
        import pytest
        pytest.skip("git not available")

    from hermes_lite.coding.context_inject import workspace_snapshot

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.com",
         "commit", "--allow-empty", "-m", "init test"],
        cwd=tmp_path, capture_output=True,
    )

    result = workspace_snapshot(tmp_path)
    assert result["ok"] is True
    assert "branch" in result
    # Should have git info even without commits


def test_workspace_snapshot_non_git(tmp_path) -> None:
    from hermes_lite.coding.context_inject import workspace_snapshot

    result = workspace_snapshot(tmp_path)
    # Non-git dirs should still return ok
    assert "branch" in result or "error" in result


def test_workspace_snapshot_counts_modified_files(tmp_path) -> None:
    import shutil
    if shutil.which("git") is None:
        import pytest
        pytest.skip("git not available")

    from hermes_lite.coding.context_inject import workspace_snapshot

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.com",
         "commit", "--allow-empty", "-m", "init test"],
        cwd=tmp_path, capture_output=True,
    )
    # Create a modified file
    (tmp_path / "changed.py").write_text("x=1")
    subprocess.run(["git", "add", "changed.py"], cwd=tmp_path, capture_output=True)

    result = workspace_snapshot(tmp_path)
    assert result.get("staged_files", 0) > 0 or result.get("modified_files", 0) > 0


def test_build_context_preamble_includes_rules(tmp_path) -> None:
    from hermes_lite.coding.context_inject import build_context_preamble

    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    (hermes_dir / "rules.md").write_text("Use pytest.\nPrefer type hints.")

    result = build_context_preamble(tmp_path)
    assert "Use pytest" in result
    assert "context" in result.lower() or "workspace" in result.lower() or "rules" in result.lower()


def test_build_context_preamble_empty_workspace(tmp_path) -> None:
    from hermes_lite.coding.context_inject import build_context_preamble

    result = build_context_preamble(tmp_path)
    # Should still return a string (possibly empty or minimal)
    assert isinstance(result, str)


def test_context_preamble_token_budget(tmp_path) -> None:
    from hermes_lite.coding.context_inject import build_context_preamble

    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    (hermes_dir / "rules.md").write_text("A" * 5000)

    result = build_context_preamble(tmp_path, max_tokens=200)
    # Should be under ~800 chars for 200 tokens
    assert len(result) < 2000
