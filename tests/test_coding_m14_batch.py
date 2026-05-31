"""Tests for M14: atomic multi-file edit_batch."""
from __future__ import annotations


def test_edit_batch_success(tmp_path) -> None:
    from hermes_lite.coding.patches import edit_batch
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "a.py").write_text("print('hello')\n")
    (tmp_path / "b.py").write_text("x = 1\n")

    result = edit_batch(ws, [
        {"path": "a.py", "old_text": "hello", "new_text": "world"},
        {"path": "b.py", "old_text": "x = 1", "new_text": "x = 2"},
    ])

    assert result["ok"] is True
    assert result["applied"] == 2
    assert result["total"] == 2
    assert "a.py" in result["files"]
    assert "b.py" in result["files"]
    assert (tmp_path / "a.py").read_text() == "print('world')\n"
    assert (tmp_path / "b.py").read_text() == "x = 2\n"


def test_edit_batch_mismatch_rollback(tmp_path) -> None:
    from hermes_lite.coding.patches import edit_batch
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "a.py").write_text("print('hello')\n")
    (tmp_path / "b.py").write_text("x = 1\n")

    result = edit_batch(ws, [
        {"path": "a.py", "old_text": "hello", "new_text": "world"},
        {"path": "b.py", "old_text": "NONEXISTENT", "new_text": "x = 2"},
    ])

    assert result["ok"] is False
    assert result["error"] == "batch_failed"
    assert result["applied"] == 0
    assert len(result["failed"]) >= 1
    # Verify no files were modified
    assert (tmp_path / "a.py").read_text() == "print('hello')\n"
    assert (tmp_path / "b.py").read_text() == "x = 1\n"


def test_edit_batch_empty_returns_error(tmp_path) -> None:
    from hermes_lite.coding.patches import edit_batch
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    result = edit_batch(ws, [])
    assert result["ok"] is False
    assert result["error"] == "empty_batch"


def test_edit_batch_fuzzy_match(tmp_path) -> None:
    from hermes_lite.coding.patches import edit_batch
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n")
    (tmp_path / "b.py").write_text("x = 1\n")

    # extra trailing whitespace — should still match with fuzzy
    result = edit_batch(ws, [
        {"path": "a.py", "old_text": "def foo():  ", "new_text": "def bar():", "fuzzy": True},
        {"path": "b.py", "old_text": "x = 1", "new_text": "x = 2"},
    ])

    assert result["ok"] is True
    assert result["applied"] == 2
    assert "def bar()" in (tmp_path / "a.py").read_text()


def test_edit_batch_missing_path(tmp_path) -> None:
    from hermes_lite.coding.patches import edit_batch
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    result = edit_batch(ws, [
        {"old_text": "hello", "new_text": "world"},
    ])
    assert result["ok"] is False
    assert result["error"] == "batch_failed"
    assert result["failed"][0]["error"] == "invalid_edit"


def test_edit_batch_single_file(tmp_path) -> None:
    from hermes_lite.coding.patches import edit_batch
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "single.py").write_text("VERSION = '1.0'\n")

    result = edit_batch(ws, [
        {"path": "single.py", "old_text": "1.0", "new_text": "2.0"},
    ])

    assert result["ok"] is True
    assert result["applied"] == 1
    assert result["total"] == 1
    assert (tmp_path / "single.py").read_text() == "VERSION = '2.0'\n"
