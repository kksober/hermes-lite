"""Conversation session persistence — save and restore message history."""
from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _session_dir(workspace_root: str) -> Path:
    return Path(workspace_root) / ".hermes" / "conversations"


def save_conversation(
    workspace_root: str,
    messages: list[dict[str, Any]],
    *,
    session_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Save message history to a conversation session file.

    Returns ``{ok, session_id, path}``.
    """
    sid = session_id or f"session-{int(time.time() * 1000)}-{random.randint(1000, 9999)}"
    sdir = _session_dir(workspace_root)
    sdir.mkdir(parents=True, exist_ok=True)

    # Convert non-dict messages to dicts
    serializable: list[dict[str, Any]] = []
    for m in messages:
        if isinstance(m, dict):
            serializable.append(m)
        elif hasattr(m, "parts"):
            parts_data: list[dict[str, Any]] = []
            for p in m.parts:
                d: dict[str, Any] = {"kind": type(p).__name__}
                if hasattr(p, "content"):
                    d["content"] = str(p.content)
                if hasattr(p, "tool_name"):
                    d["tool_name"] = p.tool_name
                if hasattr(p, "args"):
                    d["args"] = str(p.args)
                parts_data.append(d)
            serializable.append({
                "role": getattr(m, "role", "user"),
                "kind": type(m).__name__,
                "parts": parts_data,
            })
        else:
            serializable.append({"content": str(m)})

    record: dict[str, Any] = {
        "session_id": sid,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "message_count": len(serializable),
        "metadata": metadata or {},
        "messages": serializable,
    }

    path = sdir / f"{sid}.json"
    path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return {"ok": True, "session_id": sid, "path": str(path)}


def load_conversation(workspace_root: str, session_id: str) -> dict[str, Any]:
    """Load a saved conversation session.

    Returns ``{ok, session_id, messages, metadata}`` or ``{ok: False}``.
    """
    path = _session_dir(workspace_root) / f"{session_id}.json"
    if not path.exists():
        return {"ok": False, "error": "not_found", "message": f"No session: {session_id}"}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "ok": True,
            "session_id": data["session_id"],
            "saved_at": data["saved_at"],
            "message_count": data["message_count"],
            "metadata": data.get("metadata", {}),
            "messages": data["messages"],
        }
    except (json.JSONDecodeError, OSError, KeyError) as exc:
        return {"ok": False, "error": "corrupt", "message": str(exc)}


def list_conversations(workspace_root: str) -> dict[str, Any]:
    """List saved conversation sessions, newest first.

    Returns ``{ok, sessions: [{session_id, saved_at, message_count, metadata}]}``.
    """
    sdir = _session_dir(workspace_root)
    if not sdir.exists():
        return {"ok": True, "sessions": []}

    sessions: list[dict[str, Any]] = []
    for fpath in sorted(sdir.glob("*.json"), key=os.path.getmtime, reverse=True):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
            sessions.append({
                "session_id": data.get("session_id", fpath.stem),
                "saved_at": data.get("saved_at", ""),
                "message_count": data.get("message_count", 0),
                "metadata": data.get("metadata", {}),
            })
        except (json.JSONDecodeError, OSError):
            continue

    return {"ok": True, "sessions": sessions}


def delete_conversation(workspace_root: str, session_id: str) -> dict[str, Any]:
    """Delete a saved conversation session."""
    path = _session_dir(workspace_root) / f"{session_id}.json"
    if not path.exists():
        return {"ok": False, "error": "not_found"}
    path.unlink()
    return {"ok": True, "message": f"Deleted session: {session_id}"}
