"""Tests for debug_error and traceback-to-source mapping."""
from __future__ import annotations


def test_debug_error_parses_traceback(tmp_path) -> None:
    from hermes_lite.coding.testing import debug_error
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "test_app.py").write_text(
        "line1\ndef test_func():\n    x = 1\n    y = 2\n    assert x == 2\nline6\n"
    )
    traceback = (
        'Traceback (most recent call last):\n'
        f'  File "{tmp_path}/test_app.py", line 4, in test_func\n'
        '    assert x == 2\n'
        'AssertionError: assert 1 == 2\n'
    )
    ws = Workspace(tmp_path)
    result = debug_error(ws, traceback)
    assert result["ok"] is True
    assert result["frame_count"] == 1
    assert result["error_type"] == "AssertionError"
    assert "assert 1 == 2" in result["error_message"]
    frame = result["frames"][0]
    assert "test_app.py" in frame["file"]
    assert frame["line"] == 4


def test_debug_error_missing_file(tmp_path) -> None:
    from hermes_lite.coding.testing import debug_error
    from hermes_lite.coding.workspace import Workspace

    traceback = (
        '  File "/nonexistent/file.py", line 10, in broken_func\n'
        'ValueError: something broke\n'
    )
    ws = Workspace(tmp_path)
    result = debug_error(ws, traceback)
    assert result["ok"] is True
    assert result["frame_count"] == 1
    assert "(could not read" in result["frames"][0]["context"]


def test_debug_error_multiple_frames(tmp_path) -> None:
    from hermes_lite.coding.testing import debug_error
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / "a.py").write_text("def a():\n    return b()\n")
    (tmp_path / "b.py").write_text("def b():\n    raise RuntimeError('fail')\n")

    traceback = (
        '  File "a.py", line 2, in a\n'
        '    return b()\n'
        '  File "b.py", line 2, in b\n'
        '    raise RuntimeError(\'fail\')\n'
        'RuntimeError: fail\n'
    )
    ws = Workspace(tmp_path)
    result = debug_error(ws, traceback)
    assert result["frame_count"] == 2
    assert result["frames"][0]["file"] == "a.py"
    assert result["frames"][1]["file"] == "b.py"


def test_debug_error_empty_traceback(tmp_path) -> None:
    from hermes_lite.coding.testing import debug_error
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    result = debug_error(ws, "")
    assert result["ok"] is True
    assert result["frame_count"] == 0
