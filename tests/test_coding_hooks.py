"""Tests for hook execution."""
from __future__ import annotations

import json


def test_run_hooks_executes_matching_events(tmp_path) -> None:
    from hermes_lite.coding.extensibility import run_hooks
    from hermes_lite.coding.workspace import Workspace

    config_dir = tmp_path / ".hermes"
    config_dir.mkdir()
    (config_dir / "hooks.json").write_text(json.dumps({
        "hooks": [
            {"event": "pre_tool", "command": "echo 'before tool'", "enabled": True},
            {"event": "post_tool", "command": "echo 'after tool'", "enabled": True},
        ],
    }))

    ws = Workspace(tmp_path)
    result = run_hooks(ws, "pre_tool")
    assert result["ok"] is True
    assert result["executed"] == 1


def test_run_hooks_skips_disabled(tmp_path) -> None:
    from hermes_lite.coding.extensibility import run_hooks
    from hermes_lite.coding.workspace import Workspace

    config_dir = tmp_path / ".hermes"
    config_dir.mkdir()
    (config_dir / "hooks.json").write_text(json.dumps({
        "hooks": [
            {"event": "pre_tool", "command": "echo hi", "enabled": False},
        ],
    }))

    ws = Workspace(tmp_path)
    result = run_hooks(ws, "pre_tool")
    assert result["ok"] is True
    assert result["executed"] == 0


def test_run_hooks_no_config_no_error(tmp_path) -> None:
    from hermes_lite.coding.extensibility import run_hooks
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    result = run_hooks(ws, "pre_tool")
    assert result["ok"] is True
    assert result["executed"] == 0


def test_run_hooks_no_matching_events(tmp_path) -> None:
    from hermes_lite.coding.extensibility import run_hooks
    from hermes_lite.coding.workspace import Workspace

    config_dir = tmp_path / ".hermes"
    config_dir.mkdir()
    (config_dir / "hooks.json").write_text(json.dumps({
        "hooks": [
            {"event": "pre_tool", "command": "echo hi", "enabled": True},
        ],
    }))

    ws = Workspace(tmp_path)
    result = run_hooks(ws, "post_tool")
    assert result["ok"] is True
    assert result["executed"] == 0
