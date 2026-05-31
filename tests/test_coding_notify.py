"""Tests for desktop notification system."""
from __future__ import annotations


def test_notify_returns_ok() -> None:
    from hermes_lite.coding.notify import notify

    result = notify("Test", "Message")
    # Should either succeed or gracefully report platform/command issue
    assert "ok" in result
    if result["ok"]:
        assert result["title"] == "Test"
    else:
        assert "error" in result


def test_notify_if_long_below_threshold() -> None:
    from hermes_lite.coding.notify import notify_if_long

    result = notify_if_long("Task", 5.0, threshold=30.0)
    assert result["ok"] is True
    assert result.get("notified") is False


def test_notify_if_long_above_threshold() -> None:
    from hermes_lite.coding.notify import notify_if_long

    result = notify_if_long("Task", 60.0, threshold=30.0)
    assert "ok" in result


def test_system_detection() -> None:
    from hermes_lite.coding.notify import _system

    sysname = _system()
    assert sysname in ("darwin", "linux", "windows", "")
