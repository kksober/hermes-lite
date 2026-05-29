"""Tests for enhanced context: rg integration, recent changes, test association, repo map."""

from __future__ import annotations

import subprocess

import pytest


# ---------------------------------------------------------------------------
# rg availability
# ---------------------------------------------------------------------------


def test_rg_detection() -> None:
    from hermes_lite.coding.context import _has_rg

    result = _has_rg()
    assert isinstance(result, bool)
    # rg should be available in this environment
    try:
        subprocess.run(["rg", "--version"], capture_output=True, timeout=2, check=True)
        assert result is True
    except Exception:
        assert result is False


# ---------------------------------------------------------------------------
# list_files with rg
# ---------------------------------------------------------------------------


def test_list_files_uses_rg_when_available(tmp_path) -> None:
    from hermes_lite.coding.context import list_files
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# project\n", encoding="utf-8")

    result = list_files(Workspace(tmp_path))
    assert result["ok"] is True
    assert "src/app.py" in result["files"]
    assert result["method"] in ("ripgrep", "glob")


def test_list_files_skips_protected_even_with_rg(tmp_path) -> None:
    from hermes_lite.coding.context import list_files
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("ignored\n", encoding="utf-8")

    result = list_files(Workspace(tmp_path))
    assert "node_modules/pkg.js" not in result["files"]


# ---------------------------------------------------------------------------
# search_text with rg
# ---------------------------------------------------------------------------


def test_search_text_uses_rg_when_available(tmp_path) -> None:
    from hermes_lite.coding.context import search_text
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("alpha\nneedle here\n", encoding="utf-8")

    result = search_text(Workspace(tmp_path), "needle")
    assert result["ok"] is True
    assert len(result["matches"]) >= 1
    matches = result["matches"]
    assert any("needle" in m["line"] for m in matches)


def test_search_text_empty_query(tmp_path) -> None:
    from hermes_lite.coding.context import search_text
    from hermes_lite.coding.workspace import Workspace

    result = search_text(Workspace(tmp_path), "")
    assert result["ok"] is False
    assert result["error"] == "empty_query"


# ---------------------------------------------------------------------------
# rank_files — multi-factor scoring
# ---------------------------------------------------------------------------


def test_rank_files_multi_factor_scoring(tmp_path) -> None:
    from hermes_lite.coding.context import rank_files
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "user_service.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "src" / "user_utils.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "src" / "unrelated.py").write_text("pass\n", encoding="utf-8")

    result = rank_files(Workspace(tmp_path), "user_service")
    assert result["ok"] is True
    assert result["method"] == "multi_factor"
    files = result["files"]
    assert files[0]["path"] == "src/user_service.py"
    assert files[0]["score"] >= 100   # exact name match


def test_rank_files_stem_match(tmp_path) -> None:
    from hermes_lite.coding.context import rank_files
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "agents.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "unrelated.py").write_text("pass\n", encoding="utf-8")

    result = rank_files(Workspace(tmp_path), "agent")
    assert result["ok"] is True
    assert any("agents.py" in f["path"] for f in result["files"])


# ---------------------------------------------------------------------------
# recent_changes
# ---------------------------------------------------------------------------


def test_recent_changes_git_repo(tmp_path) -> None:
    from hermes_lite.coding.context import recent_changes
    from hermes_lite.coding.workspace import Workspace

    import shutil
    if shutil.which("git") is None:
        pytest.skip("git not available")

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    (tmp_path / "file1.py").write_text("a\n")
    subprocess.run(["git", "add", "file1.py"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@t.com",
                    "commit", "-m", "init"], cwd=tmp_path, capture_output=True)

    (tmp_path / "file2.py").write_text("b\n")
    subprocess.run(["git", "add", "file2.py"], cwd=tmp_path, capture_output=True)

    result = recent_changes(Workspace(tmp_path))
    assert result["ok"] is True
    assert len(result["files"]) > 0


def test_recent_changes_fallback_to_filesystem(tmp_path) -> None:
    from hermes_lite.coding.context import recent_changes
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "a.py").write_text("a\n")
    (tmp_path / "b.py").write_text("b\n")

    result = recent_changes(Workspace(tmp_path))
    assert result["ok"] is True
    # Falls back to filesystem since it's not a git repo
    assert result["source"] == "filesystem"


# ---------------------------------------------------------------------------
# find_test_files
# ---------------------------------------------------------------------------


def test_find_test_files_exact_stem_match(tmp_path) -> None:
    from hermes_lite.coding.context import find_test_files
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "auth.py").write_text("pass\n")
    (tmp_path / "tests" / "test_auth.py").write_text("pass\n")
    (tmp_path / "tests" / "test_other.py").write_text("pass\n")

    result = find_test_files(Workspace(tmp_path), "src/auth.py")
    assert result["ok"] is True
    assert result["count"] >= 1
    assert any("test_auth.py" in tf["path"] for tf in result["test_files"])


def test_find_test_files_no_match(tmp_path) -> None:
    from hermes_lite.coding.context import find_test_files
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "unique_name.py").write_text("pass\n")

    result = find_test_files(Workspace(tmp_path), "src/unique_name.py")
    assert result["ok"] is True
    assert result["count"] == 0


# ---------------------------------------------------------------------------
# repo_map_summary
# ---------------------------------------------------------------------------


def test_repo_map_summary_basic(tmp_path) -> None:
    from hermes_lite.coding.context import repo_map_summary
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "app.py").write_text("pass\n")
    (tmp_path / "README.md").write_text("# project\n")

    result = repo_map_summary(Workspace(tmp_path))
    assert result["ok"] is True
    assert result["root"] == str(tmp_path.resolve())
    assert result["file_count"] >= 2
    assert "languages" in result
    assert "important_files" in result
    assert "test_dirs" in result


def test_repo_map_summary_with_token_budget(tmp_path) -> None:
    from hermes_lite.coding.context import repo_map_summary
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "app.py").write_text("pass\n")

    result = repo_map_summary(Workspace(tmp_path), token_budget=500)
    assert result["ok"] is True


def test_repo_map_summary_without_recent(tmp_path) -> None:
    from hermes_lite.coding.context import repo_map_summary
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "app.py").write_text("pass\n")

    result = repo_map_summary(Workspace(tmp_path), include_recent=False)
    assert result["ok"] is True
    assert "recent_changes" not in result


# ---------------------------------------------------------------------------
# build_project_map with rg
# ---------------------------------------------------------------------------


def test_build_project_map_counts_languages_with_rg(tmp_path) -> None:
    from hermes_lite.coding.context import build_project_map
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "agent.py").write_text("class Agent: pass\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "config.json").write_text('{"key": "val"}\n', encoding="utf-8")

    ws = Workspace(tmp_path)
    pm = build_project_map(ws)

    assert pm["ok"] is True
    assert pm["languages"]["Python"] == 1
    assert pm["languages"]["Markdown"] == 1
    assert pm["languages"]["JSON"] == 1


# ---------------------------------------------------------------------------
# _rg_files (internal, ripple-dependent on rg)
# ---------------------------------------------------------------------------


def test_rg_files_returns_paths(tmp_path) -> None:
    from hermes_lite.coding.context import _has_rg, _rg_files
    from hermes_lite.coding.workspace import Workspace

    if not _has_rg():
        pytest.skip("rg not available")

    (tmp_path / "a.py").write_text("1\n")
    (tmp_path / "b.py").write_text("2\n")

    files = _rg_files(Workspace(tmp_path))
    assert "a.py" in files
    assert "b.py" in files


def test_rg_files_respects_limit(tmp_path) -> None:
    from hermes_lite.coding.context import _has_rg, _rg_files
    from hermes_lite.coding.workspace import Workspace

    if not _has_rg():
        pytest.skip("rg not available")

    for i in range(5):
        (tmp_path / f"file_{i}.py").write_text(f"{i}\n")

    files = _rg_files(Workspace(tmp_path), limit=3)
    assert len(files) <= 3


def test_rg_files_skips_protected(tmp_path) -> None:
    from hermes_lite.coding.context import _has_rg, _rg_files
    from hermes_lite.coding.workspace import Workspace

    if not _has_rg():
        pytest.skip("rg not available")

    (tmp_path / "ok.py").write_text("ok\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("nope\n")

    files = _rg_files(Workspace(tmp_path))
    assert "ok.py" in files
    assert "node_modules/pkg.js" not in files
