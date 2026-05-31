"""Tests for edit confirmation workflow."""
from __future__ import annotations


def test_permission_decision_has_edit_preview() -> None:
    from hermes_lite.coding.permissions import PermissionDecision

    d = PermissionDecision("ask", "write", "test.py", "edit_confirm", "msg", edit_preview="diff here")
    assert d.edit_preview == "diff here"
    assert "edit_preview" in d.to_dict()


def test_permission_policy_edit_confirm_default() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    p = PermissionPolicy()
    assert p.edit_confirm is True


def test_permission_policy_edit_confirm_false() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    p = PermissionPolicy(edit_confirm=False)
    assert p.edit_confirm is False


def test_decide_write_confirms_and_returns_allow_with_callback() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.workspace import PathCheck

    confirmed = []
    policy = PermissionPolicy(interactive=True, edit_confirm=True, confirm=lambda d: confirmed.append(d) or True)
    check = PathCheck(path="/tmp/test.py", relative_path="test.py", operation="write", ok=True, reason="ok")

    decision = policy.decide_write(check)
    # confirm callback returned True → ask_decision returns "allow"
    assert decision.action == "allow"
    assert len(confirmed) == 1
    assert confirmed[0].edit_preview == ""  # decide_write doesn't set the preview yet


def test_decide_write_returns_allow_when_no_confirm() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.workspace import PathCheck

    policy = PermissionPolicy(edit_confirm=True)  # no confirm callback
    check = PathCheck(path="/tmp/test.py", relative_path="test.py", operation="write", ok=True, reason="ok")

    decision = policy.decide_write(check)
    assert decision.action == "allow"


def test_decide_write_returns_allow_when_edit_confirm_false() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.workspace import PathCheck

    policy = PermissionPolicy(edit_confirm=False, confirm=lambda d: True)
    check = PathCheck(path="/tmp/test.py", relative_path="test.py", operation="write", ok=True, reason="ok")

    decision = policy.decide_write(check)
    assert decision.action == "allow"


def test_decide_write_denies_invalid_path() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.workspace import PathCheck

    policy = PermissionPolicy(edit_confirm=True, confirm=lambda d: True)
    check = PathCheck(path="/etc/passwd", relative_path="", operation="write", ok=False, reason="outside workspace", error="path")

    decision = policy.decide_write(check)
    assert decision.action == "deny"


def test_edit_rejected_returns_error() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy(interactive=True, confirm=lambda d: False)
    final = policy.ask_decision("write", "test.py", "edit_confirm", "Confirm?")
    assert final.action == "deny" or final.denied


def test_ask_decision_confirmed_returns_allow() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy(interactive=True, confirm=lambda d: True)
    final = policy.ask_decision("write", "test.py", "edit_confirm", "Confirm?")
    assert final.action == "allow"


def test_render_edit_preview_includes_path_and_diff() -> None:
    from hermes_lite.tools.coding import _render_edit_preview

    dry = {"matches": 1}
    result = _render_edit_preview("test.py", "old line", "new line", dry)
    assert "test.py" in result
    assert "old line" in result
    assert "new line" in result
    assert "Matches: 1" in result
