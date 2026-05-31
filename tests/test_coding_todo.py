"""Tests for agent-facing todo tracking."""
from __future__ import annotations


def test_todo_create_returns_item(tmp_path) -> None:
    from hermes_lite.coding.todo import todo_create

    result = todo_create(str(tmp_path), "Fix login bug", "Auth token refresh")
    assert result["ok"] is True
    assert result["todo"]["subject"] == "Fix login bug"
    assert result["todo"]["status"] == "pending"
    assert result["total"] == 1


def test_todo_create_empty_subject(tmp_path) -> None:
    from hermes_lite.coding.todo import todo_create

    result = todo_create(str(tmp_path), "")
    assert result["ok"] is False
    assert result["error"] == "subject_required"


def test_todo_list_returns_all(tmp_path) -> None:
    from hermes_lite.coding.todo import todo_create, todo_list

    todo_create(str(tmp_path), "Task 1")
    todo_create(str(tmp_path), "Task 2")

    result = todo_list(str(tmp_path))
    assert result["ok"] is True
    assert result["total"] == 2
    assert result["counts"]["pending"] == 2


def test_todo_list_filter_by_status(tmp_path) -> None:
    from hermes_lite.coding.todo import todo_create, todo_update, todo_list

    r = todo_create(str(tmp_path), "Task A")
    tid = r["todo"]["id"]
    todo_update(str(tmp_path), tid, status="completed")

    result = todo_list(str(tmp_path), status="pending")
    assert result["total"] == 0

    result2 = todo_list(str(tmp_path), status="completed")
    assert result2["total"] == 1


def test_todo_update_changes_fields(tmp_path) -> None:
    from hermes_lite.coding.todo import todo_create, todo_update

    r = todo_create(str(tmp_path), "Old subject")
    tid = r["todo"]["id"]

    result = todo_update(str(tmp_path), tid, status="in_progress", subject="New subject")
    assert result["ok"] is True
    assert result["todo"]["status"] == "in_progress"
    assert result["todo"]["subject"] == "New subject"


def test_todo_update_missing_id(tmp_path) -> None:
    from hermes_lite.coding.todo import todo_update

    result = todo_update(str(tmp_path), "nonexistent", status="completed")
    assert result["ok"] is False
    assert result["error"] == "todo_not_found"


def test_todo_counts_are_accurate(tmp_path) -> None:
    from hermes_lite.coding.todo import todo_create, todo_update, todo_list

    r1 = todo_create(str(tmp_path), "One")
    r2 = todo_create(str(tmp_path), "Two")
    r3 = todo_create(str(tmp_path), "Three")

    todo_update(str(tmp_path), r1["todo"]["id"], status="completed")
    todo_update(str(tmp_path), r2["todo"]["id"], status="in_progress")
    todo_update(str(tmp_path), r3["todo"]["id"], status="blocked")

    result = todo_list(str(tmp_path))
    assert result["counts"] == {
        "pending": 0, "in_progress": 1, "completed": 1, "blocked": 1,
    }


def test_todo_persists_across_calls(tmp_path) -> None:
    from hermes_lite.coding.todo import todo_create, todo_list

    todo_create(str(tmp_path), "Persistent task")
    result = todo_list(str(tmp_path))
    assert result["total"] == 1
    assert result["todos"][0]["subject"] == "Persistent task"
