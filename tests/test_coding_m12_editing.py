"""Tests for M12 P1: fuzzy matching in apply_text_patch."""
from __future__ import annotations


def test_fuzzy_exact_match_still_works(tmp_path) -> None:
    from hermes_lite.coding.patches import apply_text_patch
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "app.py").write_text("def hello():\n    return 'world'\n")

    result = apply_text_patch(
        ws, "app.py", "def hello():\n    return 'world'",
        "def hello():\n    return 'earth'", fuzzy=True,
    )
    assert result["ok"] is True
    assert result["match_strategy"] == "exact"
    content = (tmp_path / "app.py").read_text()
    assert "return 'earth'" in content


def test_fuzzy_trailing_whitespace_tolerance(tmp_path) -> None:
    from hermes_lite.coding.patches import apply_text_patch
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "app.py").write_text("def hello():  \n    return 'world'\n")

    result = apply_text_patch(
        ws, "app.py",
        "def hello():\n    return 'world'",  # no trailing ws
        "def hello():\n    return 'earth'",
        fuzzy=True,
    )
    assert result["ok"] is True
    assert result["match_strategy"] == "fuzzy"
    content = (tmp_path / "app.py").read_text()
    assert "return 'earth'" in content


def test_fuzzy_indent_tolerance(tmp_path) -> None:
    from hermes_lite.coding.patches import apply_text_patch
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "app.py").write_text("    def hello():\n        return 'world'\n")

    result = apply_text_patch(
        ws, "app.py",
        "def hello():\n    return 'world'",  # wrong indent
        "def hello():\n    return 'earth'",
        fuzzy=True,
    )
    assert result["ok"] is True
    assert result["match_strategy"] == "fuzzy"
    content = (tmp_path / "app.py").read_text()
    assert "return 'earth'" in content


def test_fuzzy_mismatch_still_reports_error(tmp_path) -> None:
    from hermes_lite.coding.patches import apply_text_patch
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "app.py").write_text("x = 1\n")

    result = apply_text_patch(
        ws, "app.py", "completely different text", "y = 2", fuzzy=True,
    )
    assert result["ok"] is False
    assert result["error"] == "patch_mismatch"


def test_fuzzy_false_preserves_old_behavior(tmp_path) -> None:
    from hermes_lite.coding.patches import apply_text_patch
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "app.py").write_text("def hello():  \n    return 'world'\n")

    result = apply_text_patch(
        ws, "app.py",
        "def hello():\n    return 'world'",
        "def hello():\n    return 'earth'",
        fuzzy=False,
    )
    assert result["ok"] is False
    assert result["error"] == "patch_mismatch"


def test_fuzzy_replace_all(tmp_path) -> None:
    from hermes_lite.coding.patches import apply_text_patch
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "app.py").write_text("TODO: fix\nx=1\nTODO: fix\n")

    result = apply_text_patch(
        ws, "app.py", "TODO: fix", "DONE", replace_all=True, fuzzy=True,
    )
    assert result["ok"] is True
    assert result["replacements"] == 2
    content = (tmp_path / "app.py").read_text()
    assert content.count("DONE") == 2
