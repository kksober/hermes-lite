"""Tests for coding context, patches, git, and diagnostics."""

from __future__ import annotations

import shutil
import subprocess

import pytest


def test_list_files_skips_protected_directories(tmp_path) -> None:
    from hermes_lite.coding.context import list_files
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("ignored\n", encoding="utf-8")

    result = list_files(Workspace(tmp_path))

    assert result["ok"] is True
    assert "src/app.py" in result["files"]
    assert "node_modules/pkg.js" not in result["files"]


def test_search_text_finds_line_matches(tmp_path) -> None:
    from hermes_lite.coding.context import search_text
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("alpha\nneedle here\n", encoding="utf-8")

    result = search_text(Workspace(tmp_path), "needle")

    assert result["ok"] is True
    assert result["matches"][0]["path"] == "src/app.py"
    assert result["matches"][0]["line_number"] == 2


def test_project_map_counts_languages_and_ranks_files(tmp_path) -> None:
    from hermes_lite.coding.context import build_project_map, rank_files
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "agent.py").write_text("class Agent: pass\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    ws = Workspace(tmp_path)
    project_map = build_project_map(ws)
    ranked = rank_files(ws, "agent")

    assert project_map["ok"] is True
    assert project_map["languages"]["Python"] == 1
    assert project_map["languages"]["Markdown"] == 1
    assert ranked["files"][0]["path"] == "src/agent.py"


def test_apply_text_patch_replaces_exact_match(tmp_path) -> None:
    from hermes_lite.coding.patches import apply_text_patch
    from hermes_lite.coding.workspace import Workspace

    path = tmp_path / "app.py"
    path.write_text("print('old')\n", encoding="utf-8")
    ws = Workspace(tmp_path)

    result = apply_text_patch(ws, "app.py", "old", "new")

    assert result["ok"] is True
    assert path.read_text(encoding="utf-8") == "print('new')\n"


def test_apply_text_patch_reports_mismatch(tmp_path) -> None:
    from hermes_lite.coding.patches import apply_text_patch
    from hermes_lite.coding.workspace import Workspace

    path = tmp_path / "app.py"
    path.write_text("print('old')\n", encoding="utf-8")

    result = apply_text_patch(Workspace(tmp_path), "app.py", "missing", "new")

    assert result["ok"] is False
    assert result["error"] == "patch_mismatch"


def test_git_status_and_diff(tmp_path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")

    from hermes_lite.coding.git import GitClient
    from hermes_lite.coding.workspace import Workspace

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True, capture_output=True)
    tracked.write_text("two\n", encoding="utf-8")

    client = GitClient(Workspace(tmp_path))
    status = client.status()
    diff = client.diff()

    assert status["ok"] is True
    assert "tracked.txt" in status["short"]
    assert diff["ok"] is True
    assert "-one" in diff["diff"]
    assert "+two" in diff["diff"]


def test_python_diagnostics_and_symbols(tmp_path) -> None:
    from hermes_lite.coding.diagnostics import diagnose_python, extract_python_symbols
    from hermes_lite.coding.workspace import Workspace

    good = tmp_path / "good.py"
    bad = tmp_path / "bad.py"
    good.write_text("class Thing:\n    def method(self):\n        return 1\n", encoding="utf-8")
    bad.write_text("def broken(:\n", encoding="utf-8")

    ws = Workspace(tmp_path)
    diagnostics = diagnose_python(ws, "bad.py")
    symbols = extract_python_symbols(ws, "good.py")

    assert diagnostics["ok"] is False
    assert diagnostics["diagnostics"][0]["severity"] == "error"
    assert {"name": "Thing", "kind": "class", "line": 1} in symbols["symbols"]
    assert {"name": "method", "kind": "function", "line": 2} in symbols["symbols"]
