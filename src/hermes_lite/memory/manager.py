"""Memory manager — SQLite-backed persistent memory with deduplication.

Memory entries are stored in a SQLite database and can be injected into the
system prompt.  Duplicate detection uses simple content similarity (>90%).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlite_utils


@dataclass
class MemoryEntry:
    """A single memory record."""

    id: int
    target: str
    content: str
    created_at: str
    updated_at: str


class MemoryManager:
    """SQLite-backed memory with deduplication and prompt injection.

    Schema::

        CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target TEXT NOT NULL,      -- 'user' or 'memory'
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

    Usage::

        mm = MemoryManager()
        mm.save("User prefers Python over JavaScript", target="user")
        prompt_injection = mm.inject(limit=10)
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Initialise memory store.

        Args:
            db_path: Path to SQLite database file.  Defaults to
                ``~/.local/share/hermes-lite/memory.db`` (XDG-compliant).
                Pass ``":memory:"`` for an in-memory database (used in tests).
        """
        if db_path is None:
            # In test environments, use :memory: to keep tests isolated.
            # Otherwise default to XDG-compliant persistent storage.
            import sys

            if "pytest" in sys.modules:
                db_path = ":memory:"
            else:
                xdg_data = os.environ.get(
                    "XDG_DATA_HOME", str(Path.home() / ".local" / "share")
                )
                db_path = Path(xdg_data) / "hermes-lite" / "memory.db"
        self._db_path = str(db_path)
        # Ensure parent directory exists for file-based databases
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite_utils.Database(self._db_path)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create the memories table if it doesn't exist."""
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # Ensure indexes exist
        self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_target
            ON memories(target)
        """)

    def _now(self) -> str:
        """Return current UTC timestamp as ISO string."""
        return datetime.now(timezone.utc).isoformat()

    def _similarity(self, a: str, b: str) -> float:
        """Simple Jaccard-like word overlap similarity.

        Returns a float in [0.0, 1.0].
        """
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union)

    def save(self, content: str, target: str = "memory") -> int:
        """Save a memory entry. Skips if >90% similar to an existing entry.

        Args:
            content: The memory content to store.
            target: Category — 'user' or 'memory'.

        Returns:
            The row id of the saved (or existing) entry.
        """
        # Deduplication check
        existing = list(self._db.query(
            "SELECT id, content FROM memories WHERE target = ?", [target]
        ))
        for row in existing:
            if self._similarity(content, row["content"]) >= 0.9:
                # Update timestamp of existing row
                now = self._now()
                self._db.execute(
                    "UPDATE memories SET updated_at = ? WHERE id = ?",
                    [now, row["id"]],
                )
                return row["id"]

        now = self._now()
        self._db.execute(
            "INSERT INTO memories (target, content, created_at, updated_at) VALUES (?, ?, ?, ?)",
            [target, content, now, now],
        )
        cursor = self._db.execute("SELECT last_insert_rowid()")
        row = cursor.fetchone()
        return row[0] if row else -1

    def inject(self, limit: int = 10) -> str:
        """Return a compact memory string suitable for system prompt injection.

        Args:
            limit: Maximum number of recent memories to include.

        Returns:
            Formatted string like::

                <memory>
                [user] User prefers Python over JavaScript
                [memory] Project uses FastAPI
                </memory>
        """
        rows = list(self._db.query(
            "SELECT target, content FROM memories ORDER BY updated_at DESC LIMIT ?",
            [limit],
        ))
        if not rows:
            return ""
        lines = ["<memory>"]
        for row in rows:
            lines.append(f"[{row['target']}] {row['content']}")
        lines.append("</memory>")
        return "\n".join(lines)

    def replace(self, old_text: str, new_text: str) -> bool:
        """Replace a memory entry by targeted content match.

        Args:
            old_text: Exact content to find and replace.
            new_text: New content to substitute.

        Returns:
            True if a matching entry was found and updated.
        """
        cursor = self._db.execute(
            "SELECT id FROM memories WHERE content = ? LIMIT 1", [old_text]
        )
        row = cursor.fetchone()
        if row is None:
            return False
        now = self._now()
        self._db.execute(
            "UPDATE memories SET content = ?, updated_at = ? WHERE id = ?",
            [new_text, now, row[0]],
        )
        return True

    def remove(self, old_text: str) -> bool:
        """Delete a memory entry by exact content match.

        Args:
            old_text: Exact content to remove.

        Returns:
            True if a matching entry was found and deleted.
        """
        cursor = self._db.execute(
            "SELECT id FROM memories WHERE content = ? LIMIT 1", [old_text]
        )
        row = cursor.fetchone()
        if row is None:
            return False
        self._db.execute("DELETE FROM memories WHERE id = ?", [row[0]])
        return True

    def list_all(self) -> list[MemoryEntry]:
        """Return all memory entries.

        Returns:
            List of MemoryEntry dataclass instances.
        """
        rows = self._db.query(
            "SELECT id, target, content, created_at, updated_at FROM memories ORDER BY updated_at DESC"
        )
        return [
            MemoryEntry(
                id=row["id"],
                target=row["target"],
                content=row["content"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def clear(self) -> None:
        """Remove all memory entries."""
        self._db.execute("DELETE FROM memories")
