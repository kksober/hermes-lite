"""Tests for permission policy improvements: timeout, headless."""
from __future__ import annotations


def test_policy_has_ask_timeout_default() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    assert policy.ask_timeout == 60.0


def test_policy_has_headless_webhook_default() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    assert policy.headless_webhook == ""


def test_policy_summary_includes_timeout() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy(ask_timeout=30.0, headless_webhook="https://example.com/hook")
    summary = policy.summary()
    assert summary["ask_timeout"] == 30.0
    assert summary["headless"] is True


def test_policy_summary_headless_false_by_default() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    summary = policy.summary()
    assert summary["headless"] is False


def test_policy_custom_timeout() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy(ask_timeout=10.0)
    assert policy.ask_timeout == 10.0
