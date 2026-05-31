"""Tests for conversation session persistence."""
from __future__ import annotations


def test_save_and_load_conversation(tmp_path) -> None:
    from hermes_lite.coding.conversation_store import save_conversation, load_conversation

    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    saved = save_conversation(str(tmp_path), messages)
    assert saved["ok"] is True
    assert saved["session_id"].startswith("session-")

    loaded = load_conversation(str(tmp_path), saved["session_id"])
    assert loaded["ok"] is True
    assert loaded["message_count"] == 3
    assert len(loaded["messages"]) == 3


def test_load_conversation_not_found(tmp_path) -> None:
    from hermes_lite.coding.conversation_store import load_conversation

    result = load_conversation(str(tmp_path), "nonexistent")
    assert result["ok"] is False
    assert result["error"] == "not_found"


def test_list_conversations(tmp_path) -> None:
    from hermes_lite.coding.conversation_store import save_conversation, list_conversations

    save_conversation(str(tmp_path), [{"role": "user", "content": "a"}])
    save_conversation(str(tmp_path), [{"role": "user", "content": "b"}])

    result = list_conversations(str(tmp_path))
    assert result["ok"] is True
    assert len(result["sessions"]) == 2


def test_list_conversations_empty(tmp_path) -> None:
    from hermes_lite.coding.conversation_store import list_conversations

    result = list_conversations(str(tmp_path))
    assert result["ok"] is True
    assert result["sessions"] == []


def test_delete_conversation(tmp_path) -> None:
    from hermes_lite.coding.conversation_store import save_conversation, delete_conversation, list_conversations

    saved = save_conversation(str(tmp_path), [{"role": "user", "content": "test"}])
    result = delete_conversation(str(tmp_path), saved["session_id"])
    assert result["ok"] is True
    assert len(list_conversations(str(tmp_path))["sessions"]) == 0


def test_delete_conversation_not_found(tmp_path) -> None:
    from hermes_lite.coding.conversation_store import delete_conversation

    result = delete_conversation(str(tmp_path), "nonexistent")
    assert result["ok"] is False
    assert result["error"] == "not_found"


def test_save_with_custom_session_id(tmp_path) -> None:
    from hermes_lite.coding.conversation_store import save_conversation, load_conversation

    saved = save_conversation(str(tmp_path), [], session_id="my-session")
    assert saved["session_id"] == "my-session"
    loaded = load_conversation(str(tmp_path), "my-session")
    assert loaded["ok"] is True
