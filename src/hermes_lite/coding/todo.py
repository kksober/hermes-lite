"""Agent-facing task tracking — persisted as JSONL.

Provides ``todo_create``, ``todo_update``, and ``todo_list`` functions
that the agent can call to manage its own work across turns.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


def _todo_path(workspace_root: str) -> Path:
    hermes_dir = Path(workspace_root) / ".hermes"
    if not hermes_dir.exists():
        hermes_dir.mkdir(parents=True, exist_ok=True)
    return hermes_dir / "todos.jsonl"


def _read_todos(workspace_root: str) -> list[dict[str, Any]]:
    path = _todo_path(workspace_root)
    if not path.exists():
        return []
    todos: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    todos.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return todos


def _write_todos(workspace_root: str, todos: list[dict[str, Any]]) -> None:
    path = _todo_path(workspace_root)
    with open(path, "w", encoding="utf-8") as fh:
        for t in todos:
            fh.write(json.dumps(t, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def todo_create(
    workspace_root: str,
    subject: str,
    description: str = "",
    *,
    priority: str = "medium",
) -> dict[str, object]:
    """Create a new todo item."""
    if not subject.strip():
        return {"ok": False, "error": "subject_required"}

    todos = _read_todos(workspace_root)
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    item: dict[str, Any] = {
        "id": uuid.uuid4().hex[:12],
        "subject": subject.strip(),
        "description": description.strip(),
        "status": "pending",
        "priority": priority,
        "created_at": now,
        "updated_at": now,
    }
    todos.append(item)
    _write_todos(workspace_root, todos)
    return {"ok": True, "todo": item, "total": len(todos)}


def todo_update(
    workspace_root: str,
    todo_id: str,
    *,
    status: str = "",
    subject: str = "",
    description: str = "",
    priority: str = "",
) -> dict[str, object]:
    """Update a todo item by ID."""
    todos = _read_todos(workspace_root)
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    for t in todos:
        if t["id"] == todo_id:
            if status:
                t["status"] = status
            if subject:
                t["subject"] = subject
            if description:
                t["description"] = description
            if priority:
                t["priority"] = priority
            t["updated_at"] = now
            _write_todos(workspace_root, todos)
            return {"ok": True, "todo": t, "total": len(todos)}
    return {"ok": False, "error": "todo_not_found", "todo_id": todo_id}


def todo_list(
    workspace_root: str,
    *,
    status: str = "",
    priority: str = "",
) -> dict[str, object]:
    """List todos, optionally filtered by status or priority."""
    todos = _read_todos(workspace_root)
    if status:
        todos = [t for t in todos if t["status"] == status]
    if priority:
        todos = [t for t in todos if t["priority"] == priority]
    return {
        "ok": True,
        "todos": todos,
        "total": len(todos),
        "counts": {
            "pending": sum(1 for t in todos if t["status"] == "pending"),
            "in_progress": sum(1 for t in todos if t["status"] == "in_progress"),
            "completed": sum(1 for t in todos if t["status"] == "completed"),
            "blocked": sum(1 for t in todos if t["status"] == "blocked"),
        },
    }
