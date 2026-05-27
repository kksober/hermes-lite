"""Tests for the session management system."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


MESSAGES_JSON = json.dumps([
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi! How can I help?"},
])


class TestSessionManager:
    """Test SessionManager — save, load, search, delete."""

    def test_save_and_load(self) -> None:
        """Test saving a session and loading it back."""
        from hermes_lite.sessions import SessionManager

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "sessions.db")
            sm = SessionManager(db_path=db_path)

            sm.save("s1", "Debug session", MESSAGES_JSON)

            session = sm.load("s1")
            assert session is not None
            assert session["id"] == "s1"
            assert session["title"] == "Debug session"
            assert session["messages"] == MESSAGES_JSON
            assert "created_at" in session
            assert "updated_at" in session

    def test_load_missing(self) -> None:
        """Test loading a non-existent session returns None."""
        from hermes_lite.sessions import SessionManager

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "sessions.db")
            sm = SessionManager(db_path=db_path)
            assert sm.load("nonexistent") is None

    def test_save_update(self) -> None:
        """Test that saving with an existing id updates the session."""
        from hermes_lite.sessions import SessionManager

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "sessions.db")
            sm = SessionManager(db_path=db_path)

            sm.save("s1", "Original", MESSAGES_JSON)

            updated_json = json.dumps([
                {"role": "user", "content": "Updated message"},
            ])
            sm.save("s1", "Updated Title", updated_json)

            session = sm.load("s1")
            assert session is not None
            assert session["title"] == "Updated Title"
            assert session["messages"] == updated_json

    def test_list_recent(self) -> None:
        """Test listing recent sessions."""
        from hermes_lite.sessions import SessionManager

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "sessions.db")
            sm = SessionManager(db_path=db_path)

            sm.save("s1", "First", MESSAGES_JSON)
            sm.save("s2", "Second", MESSAGES_JSON)
            sm.save("s3", "Third", MESSAGES_JSON)

            recent = sm.list_recent(limit=2)
            assert len(recent) == 2
            # Most recently updated first
            assert recent[0]["id"] == "s3"

    def test_list_recent_default_limit(self) -> None:
        """Test list_recent with default limit (20)."""
        from hermes_lite.sessions import SessionManager

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "sessions.db")
            sm = SessionManager(db_path=db_path)

            sm.save("s1", "Test", MESSAGES_JSON)
            recent = sm.list_recent()
            assert len(recent) == 1

    def test_search(self) -> None:
        """Test full-text search across sessions."""
        from hermes_lite.sessions import SessionManager

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "sessions.db")
            sm = SessionManager(db_path=db_path)

            sm.save("s1", "Debug session", MESSAGES_JSON)
            sm.save(
                "s2",
                "Error handling",
                json.dumps([
                    {"role": "user", "content": "I see an error in the logs"},
                ]),
            )

            # Search in title
            results = sm.search("Debug")
            assert len(results) == 1
            assert results[0]["id"] == "s1"

            # Search in messages
            results = sm.search("error")
            assert len(results) >= 1
            assert any(r["id"] == "s2" for r in results)

    def test_search_no_match(self) -> None:
        """Test search returns empty list when nothing matches."""
        from hermes_lite.sessions import SessionManager

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "sessions.db")
            sm = SessionManager(db_path=db_path)

            sm.save("s1", "Test", MESSAGES_JSON)

            results = sm.search("zzz_nonexistent_zzz")
            assert results == []

    def test_delete(self) -> None:
        """Test deleting a session."""
        from hermes_lite.sessions import SessionManager

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "sessions.db")
            sm = SessionManager(db_path=db_path)

            sm.save("s1", "Test", MESSAGES_JSON)
            assert sm.load("s1") is not None

            result = sm.delete("s1")
            assert result is True
            assert sm.load("s1") is None

    def test_delete_missing(self) -> None:
        """Test deleting a non-existent session returns False."""
        from hermes_lite.sessions import SessionManager

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "sessions.db")
            sm = SessionManager(db_path=db_path)
            assert sm.delete("nonexistent") is False

    def test_db_persistence(self) -> None:
        """Test that sessions survive reopening the database."""
        from hermes_lite.sessions import SessionManager

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "sessions.db")

            # First instance
            sm1 = SessionManager(db_path=db_path)
            sm1.save("s1", "Persistent", MESSAGES_JSON)

            # Second instance — same file, should see the saved data
            sm2 = SessionManager(db_path=db_path)
            session = sm2.load("s1")
            assert session is not None
            assert session["title"] == "Persistent"

    def test_empty_messages(self) -> None:
        """Test saving a session with empty messages."""
        from hermes_lite.sessions import SessionManager

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "sessions.db")
            sm = SessionManager(db_path=db_path)

            sm.save("empty", "Empty session", "[]")
            session = sm.load("empty")
            assert session is not None
            assert session["messages"] == "[]"
