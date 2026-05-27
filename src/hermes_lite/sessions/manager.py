"""Session manager — SQLite-backed session persistence with FTS5 search.

Sessions are stored as JSON text blobs with metadata columns.  A separate
FTS5 virtual table enables full-text search across titles and content.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlite_utils


class SessionManager:
    """Persist and search conversation sessions using SQLite + FTS5.

    Schema::

        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            messages TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE sessions_fts USING fts5(
            title, messages, content='sessions', content_rowid='rowid'
        );

    Usage::

        sm = SessionManager()
        sm.save("abc123", "Debug session", json.dumps([...]))
        session = sm.load("abc123")
        results = sm.search("error handling")
    """

    def __init__(self, db_path: str = "sessions/sessions.db") -> None:
        """Initialise session store.

        Args:
            db_path: Path to the SQLite database file.  Parent directories
                     are created automatically.
        """
        self._db_path = str(db_path)
        db_file = Path(self._db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite_utils.Database(self._db_path)
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        """Create tables and triggers if they don't exist."""
        # Enable WAL mode so multiple connections can coexist
        self._db.execute("PRAGMA journal_mode=WAL")

        self._db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                messages TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self._db.conn.commit()

        # FTS5 virtual table — external content so we don't duplicate data
        self._db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
                title, messages, content='sessions', content_rowid='rowid'
            )
        """)

        # Triggers to keep FTS index in sync
        self._db.execute("""
            CREATE TRIGGER IF NOT EXISTS sessions_ai AFTER INSERT ON sessions BEGIN
                INSERT INTO sessions_fts(rowid, title, messages)
                VALUES (new.rowid, new.title, new.messages);
            END
        """)
        self._db.execute("""
            CREATE TRIGGER IF NOT EXISTS sessions_ad AFTER DELETE ON sessions BEGIN
                INSERT INTO sessions_fts(sessions_fts, rowid, title, messages)
                VALUES ('delete', old.rowid, old.title, old.messages);
            END
        """)
        self._db.execute("""
            CREATE TRIGGER IF NOT EXISTS sessions_au AFTER UPDATE ON sessions BEGIN
                INSERT INTO sessions_fts(sessions_fts, rowid, title, messages)
                VALUES ('delete', old.rowid, old.title, old.messages);
                INSERT INTO sessions_fts(rowid, title, messages)
                VALUES (new.rowid, new.title, new.messages);
            END
        """)

    def _now(self) -> str:
        """Return current UTC timestamp as ISO string."""
        return datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, session_id: str, title: str, messages_json: str) -> None:
        """Persist (insert or upsert) a session.

        Args:
            session_id: Unique session identifier.
            title: Human-readable session title.
            messages_json: JSON-serialised list of messages.
        """
        now = self._now()
        existing = list(self._db.query(
            "SELECT id FROM sessions WHERE id = ?", [session_id]
        ))

        if existing:
            self._db.execute(
                "UPDATE sessions SET title = ?, messages = ?, updated_at = ? WHERE id = ?",
                [title, messages_json, now, session_id],
            )
        else:
            self._db.execute(
                "INSERT INTO sessions (id, title, messages, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                [session_id, title, messages_json, now, now],
            )
        self._db.conn.commit()

    def load(self, session_id: str) -> dict[str, Any] | None:
        """Load a session by id.

        Args:
            session_id: Unique session identifier.

        Returns:
            A dict with keys ``id``, ``title``, ``messages``, ``created_at``,
            ``updated_at``, or ``None`` if not found.
        """
        rows = list(self._db.query(
            "SELECT id, title, messages, created_at, updated_at FROM sessions WHERE id = ?",
            [session_id],
        ))
        if not rows:
            return None
        row = rows[0]
        return {
            "id": row["id"],
            "title": row["title"],
            "messages": row["messages"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the most recently updated sessions.

        Args:
            limit: Maximum number of sessions to return.

        Returns:
            List of session dicts ordered by ``updated_at`` descending.
        """
        rows = self._db.query(
            "SELECT id, title, messages, created_at, updated_at FROM sessions "
            "ORDER BY updated_at DESC LIMIT ?",
            [limit],
        )
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "messages": row["messages"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def search(self, query: str) -> list[dict[str, Any]]:
        """Full-text search across session titles and messages.

        Args:
            query: Search query string (supports FTS5 syntax).

        Returns:
            List of matching session dicts with an extra ``rank`` key.
        """
        escaped = query.replace('"', '""')
        rows = self._db.query(
            """
            SELECT s.id, s.title, s.messages, s.created_at, s.updated_at, rank
            FROM sessions_fts f
            JOIN sessions s ON f.rowid = s.rowid
            WHERE sessions_fts MATCH ?
            ORDER BY rank
            """,
            [f'"{escaped}"'],
        )
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "messages": row["messages"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "rank": row["rank"],
            }
            for row in rows
        ]

    def delete(self, session_id: str) -> bool:
        """Delete a session by id.

        Args:
            session_id: Unique session identifier.

        Returns:
            ``True`` if a session was deleted, ``False`` if it didn't exist.
        """
        existing = list(self._db.query(
            "SELECT id FROM sessions WHERE id = ?", [session_id]
        ))
        if not existing:
            return False
        self._db.execute("DELETE FROM sessions WHERE id = ?", [session_id])
        self._db.conn.commit()
        return True
