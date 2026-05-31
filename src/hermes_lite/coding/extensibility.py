"""Local hook and external tool configuration support."""

from __future__ import annotations

import json
import shlex
import subprocess
from typing import Any

from hermes_lite.coding.workspace import Workspace


def load_external_tools(workspace: Workspace, path: str = ".hermes/tools.json") -> dict[str, object]:
    """Load external tool declarations without executing them."""
    loaded = _load_json_config(workspace, path, missing_key="tools")
    if not loaded["ok"]:
        return loaded
    tools = []
    for item in loaded.get("tools", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        command = str(item.get("command", "")).strip()
        if not name or not command:
            continue
        tools.append({
            "name": name,
            "description": str(item.get("description", "")),
            "command": command,
            "enabled": bool(item.get("enabled", True)),
        })
    return {"ok": True, "config_path": path, "tools": tools}


def hook_status(workspace: Workspace, path: str = ".hermes/hooks.json") -> dict[str, object]:
    """Load hook declarations and report their status without running them."""
    loaded = _load_json_config(workspace, path, missing_key="hooks")
    if not loaded["ok"]:
        return loaded
    hooks = []
    for item in loaded.get("hooks", []):
        if not isinstance(item, dict):
            continue
        event = str(item.get("event", "")).strip()
        command = str(item.get("command", "")).strip()
        if not event or not command:
            continue
        hooks.append({
            "event": event,
            "command": command,
            "enabled": bool(item.get("enabled", True)),
        })
    return {"ok": True, "config_path": path, "hooks": hooks}


def load_mcp_servers(workspace: Workspace, path: str = ".hermes/mcp.json") -> dict[str, object]:
    """Load MCP server declarations without starting processes."""
    loaded = _load_json_config(workspace, path, missing_key="servers")
    if not loaded["ok"]:
        return loaded
    servers = []
    for item in loaded.get("servers", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        command = str(item.get("command", "")).strip()
        if not name or not command:
            continue
        servers.append({
            "name": name,
            "command": command,
            "args": list(item.get("args", [])) if isinstance(item.get("args", []), list) else [],
            "enabled": bool(item.get("enabled", True)),
        })
    return {"ok": True, "config_path": path, "servers": servers}


def run_hooks(workspace: Workspace, event: str, *, path: str = ".hermes/hooks.json") -> dict[str, object]:
    """Execute all enabled hooks matching *event*.

    Supported events: ``pre_tool``, ``post_tool``, ``pre_command``, ``post_edit``.
    """
    loaded = hook_status(workspace, path=path)
    if not loaded.get("ok"):
        return loaded
    matching = [h for h in loaded.get("hooks", []) if h["event"] == event and h["enabled"]]
    results = []
    for hook in matching:
        result = _run_single_hook(hook, workspace)
        results.append(result)
    return {
        "ok": True,
        "event": event,
        "executed": len(results),
        "results": results,
    }


def _run_single_hook(hook: dict[str, Any], workspace: Workspace) -> dict[str, object]:
    """Execute a single hook command."""
    cmd_str = str(hook.get("command", ""))
    if not cmd_str:
        return {"ok": False, "error": "empty_command", "hook_event": hook.get("event")}
    try:
        proc = subprocess.run(
            cmd_str, shell=True, cwd=str(workspace.root),
            capture_output=True, text=True, timeout=30,
        )
        return {
            "ok": True,
            "event": hook.get("event"),
            "command": cmd_str,
            "returncode": proc.returncode,
            "stdout": proc.stdout[:2000],
            "stderr": proc.stderr[:1000],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "hook_event": hook.get("event")}
    except Exception as exc:
        return {"ok": False, "error": "execution_failed", "detail": str(exc), "hook_event": hook.get("event")}


def _load_json_config(workspace: Workspace, path: str, *, missing_key: str) -> dict[str, Any]:
    check = workspace.resolve(path, operation="read")
    if not check.ok:
        return check.to_dict()
    if not check.path.exists():
        return {"ok": True, "config_path": path, missing_key: []}
    try:
        data = json.loads(check.path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": "invalid_json", "config_path": path, "message": str(exc)}
    if not isinstance(data, dict):
        return {"ok": False, "error": "invalid_config", "config_path": path}
    data["ok"] = True
    data["config_path"] = path
    data.setdefault(missing_key, [])
    return data
