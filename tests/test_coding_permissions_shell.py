"""Tests for coding permissions and shell execution."""

from __future__ import annotations

import shlex
import sys


def test_policy_denies_destructive_command() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    decision = policy.decide_command("rm -rf build")

    assert decision.allowed is False
    assert decision.reason == "destructive_command"


def test_policy_denies_shell_control_operators() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    decision = policy.decide_command("echo hi && rm -rf build")

    assert decision.allowed is False
    assert decision.reason == "shell_control_operator"


def test_policy_allows_safe_python_command() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    decision = policy.decide_command(f"{shlex.quote(sys.executable)} -c \"print('hi')\"")

    assert decision.allowed is True
    assert decision.reason == "safe_command"


def test_command_runner_executes_inside_workspace(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.shell import CommandRunner
    from hermes_lite.coding.workspace import Workspace

    runner = CommandRunner(Workspace(tmp_path), PermissionPolicy())
    result = runner.run(f"{shlex.quote(sys.executable)} -c \"print('hello')\"")

    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "hello"
    assert result["cwd"] == str(tmp_path.resolve())


def test_command_runner_denies_unsafe_command(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.shell import CommandRunner
    from hermes_lite.coding.workspace import Workspace

    runner = CommandRunner(Workspace(tmp_path), PermissionPolicy())
    result = runner.run("rm -rf build")

    assert result["ok"] is False
    assert result["error"] == "permission_denied"
    assert result["reason"] == "destructive_command"


def test_command_runner_truncates_output(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.shell import CommandRunner
    from hermes_lite.coding.workspace import Workspace

    runner = CommandRunner(Workspace(tmp_path), PermissionPolicy(), max_output_chars=8)
    result = runner.run(f"{shlex.quote(sys.executable)} -c \"print('abcdefghijklmnop')\"")

    assert result["ok"] is True
    assert result["truncated"] is True
    assert len(result["stdout"]) <= 8


def test_command_runner_reports_timeout(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.shell import CommandRunner
    from hermes_lite.coding.workspace import Workspace

    runner = CommandRunner(Workspace(tmp_path), PermissionPolicy(), timeout_seconds=0.05)
    result = runner.run(f"{shlex.quote(sys.executable)} -c \"import time; time.sleep(1)\"")

    assert result["ok"] is False
    assert result["timed_out"] is True
    assert result["error"] == "timeout"
