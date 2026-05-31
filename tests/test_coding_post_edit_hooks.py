"""Tests for post-edit hook auto-triggering."""
from __future__ import annotations

import json


def test_run_post_edit_hooks_no_config(tmp_path) -> None:
    from hermes_lite.coding.extensibility import run_post_edit_hooks
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    result = run_post_edit_hooks(ws, "test.py")
    assert result["ok"] is True
    assert result["ran"] == 0


def test_run_post_edit_hooks_runs_matching(tmp_path) -> None:
    from hermes_lite.coding.extensibility import run_post_edit_hooks
    from hermes_lite.coding.workspace import Workspace

    hooks_dir = tmp_path / ".hermes"
    hooks_dir.mkdir()
    hooks_config = {
        "hooks": [
            {
                "event": "post_edit",
                "command": "echo 'linting {file}'",
                "enabled": True,
                "auto_trigger": ["post_edit"],
            },
        ]
    }
    (hooks_dir / "hooks.json").write_text(json.dumps(hooks_config))

    ws = Workspace(tmp_path)
    result = run_post_edit_hooks(ws, "src/main.py")
    assert result["ok"] is True
    assert result["ran"] == 1
    assert result["failed"] == 0


def test_run_post_edit_hooks_skips_disabled(tmp_path) -> None:
    from hermes_lite.coding.extensibility import run_post_edit_hooks
    from hermes_lite.coding.workspace import Workspace

    hooks_dir = tmp_path / ".hermes"
    hooks_dir.mkdir()
    hooks_config = {
        "hooks": [
            {
                "event": "post_edit",
                "command": "echo 'disabled'",
                "enabled": False,
                "auto_trigger": ["post_edit"],
            },
        ]
    }
    (hooks_dir / "hooks.json").write_text(json.dumps(hooks_config))

    ws = Workspace(tmp_path)
    result = run_post_edit_hooks(ws, "test.py")
    assert result["ok"] is True
    assert result["ran"] == 0


def test_run_post_edit_hooks_substitutes_file(tmp_path) -> None:
    from hermes_lite.coding.extensibility import run_post_edit_hooks
    from hermes_lite.coding.workspace import Workspace

    hooks_dir = tmp_path / ".hermes"
    hooks_dir.mkdir()
    hooks_config = {
        "hooks": [
            {
                "event": "post_edit",
                "command": "echo 'formatted: {file}'",
                "enabled": True,
                "auto_trigger": ["post_edit"],
            },
        ]
    }
    (hooks_dir / "hooks.json").write_text(json.dumps(hooks_config))

    ws = Workspace(tmp_path)
    result = run_post_edit_hooks(ws, "src/app.py")
    assert result["ok"] is True
    stdout = result["results"][0].get("stdout", "")
    assert "src/app.py" in stdout


def test_run_post_edit_hooks_no_auto_trigger(tmp_path) -> None:
    from hermes_lite.coding.extensibility import run_post_edit_hooks
    from hermes_lite.coding.workspace import Workspace

    hooks_dir = tmp_path / ".hermes"
    hooks_dir.mkdir()
    hooks_config = {
        "hooks": [
            {
                "event": "pre_commit",
                "command": "black .",
                "enabled": True,
            },
        ]
    }
    (hooks_dir / "hooks.json").write_text(json.dumps(hooks_config))

    ws = Workspace(tmp_path)
    result = run_post_edit_hooks(ws, "test.py")
    assert result["ok"] is True
    assert result["ran"] == 0
