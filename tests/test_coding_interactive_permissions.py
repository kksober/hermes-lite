"""Tests for interactive permissions, audit logging, and session authorization."""

from __future__ import annotations

import shlex
import sys


# ---------------------------------------------------------------------------
# AuditLogger
# ---------------------------------------------------------------------------

def test_audit_logger_records_entries() -> None:
    from hermes_lite.coding.audit import AuditLogger

    logger = AuditLogger()
    logger.record("permission", "command", "ls -la", "allow", "safe_command")
    logger.record("permission", "command", "rm -rf /", "deny", "destructive_command")

    assert len(logger.entries()) == 2
    assert logger.entries()[0].decision == "allow"
    assert logger.entries()[1].decision == "deny"


def test_audit_logger_summary() -> None:
    from hermes_lite.coding.audit import AuditLogger

    logger = AuditLogger()
    logger.record("permission", "command", "ls", "allow", "safe")
    logger.record("permission", "command", "curl ...", "ask", "network")
    logger.record("permission", "command", "rm ...", "deny", "destructive")

    s = logger.summary()
    assert s["total_entries"] == 3
    assert s["allowed"] == 1
    assert s["asked"] == 1
    assert s["denied"] == 1


def test_audit_logger_recent() -> None:
    from hermes_lite.coding.audit import AuditLogger

    logger = AuditLogger()
    for i in range(10):
        logger.record("permission", "command", f"cmd{i}", "allow", "safe")

    recent = logger.recent(3)
    assert len(recent) == 3
    assert recent[-1].target == "cmd9"


def test_audit_logger_writes_to_file(tmp_path) -> None:
    from hermes_lite.coding.audit import AuditLogger

    log_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_path=log_path)
    logger.record("permission", "command", "ls", "allow", "safe")

    assert log_path.exists()
    content = log_path.read_text()
    assert "ls" in content
    assert "allow" in content


# ---------------------------------------------------------------------------
# PermissionDecision
# ---------------------------------------------------------------------------

def test_permission_decision_properties() -> None:
    from hermes_lite.coding.permissions import PermissionDecision

    allow = PermissionDecision("allow", "op", "target", "reason")
    ask = PermissionDecision("ask", "op", "target", "reason")
    deny = PermissionDecision("deny", "op", "target", "reason")

    assert allow.allowed is True
    assert allow.requires_approval is False
    assert allow.denied is False

    assert ask.allowed is False
    assert ask.requires_approval is True
    assert ask.denied is False

    assert deny.allowed is False
    assert deny.requires_approval is False
    assert deny.denied is True


def test_permission_decision_to_dict() -> None:
    from hermes_lite.coding.permissions import PermissionDecision

    d = PermissionDecision("ask", "command", "curl example.com", "network_command", "Network access needed.")
    result = d.to_dict()
    assert result["action"] == "ask"
    assert result["allowed"] is False
    assert result["requires_approval"] is True
    assert result["message"] == "Network access needed."


# ---------------------------------------------------------------------------
# PermissionPolicy — basic (non-interactive)
# ---------------------------------------------------------------------------

def test_policy_denies_destructive_command() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    decision = policy.decide_command("rm -rf build")
    assert decision.denied is True
    assert decision.reason == "destructive_command"


def test_policy_denies_shell_control_operators_non_interactive() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    decision = policy.decide_command("echo hi && rm -rf build")
    assert decision.denied is True
    assert decision.reason == "shell_control_operator"


def test_policy_allows_safe_python_command() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    decision = policy.decide_command(f"{shlex.quote(sys.executable)} -c \"print('hi')\"")
    assert decision.allowed is True
    assert decision.reason == "safe_command"


def test_policy_denies_command_substitution() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    decision = policy.decide_command("echo $(whoami)")
    assert decision.denied is True
    assert decision.reason == "command_substitution"


def test_policy_denies_backtick_substitution() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    decision = policy.decide_command("echo `whoami`")
    assert decision.denied is True
    assert decision.reason == "command_substitution"


def test_policy_denies_package_install_non_interactive() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    decision = policy.decide_command("pip install requests")
    assert decision.denied is True
    assert decision.reason == "network_command"


def test_policy_denies_network_command_non_interactive() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    decision = policy.decide_command("curl https://example.com")
    assert decision.denied is True
    assert decision.reason == "network_command"


def test_policy_allows_safe_git_command() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    decision = policy.decide_command("git status")
    assert decision.allowed is True


def test_policy_denies_risky_git_non_interactive() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    decision = policy.decide_command("git reset --hard")
    assert decision.denied is True
    assert decision.reason == "risky_git_command"


# ---------------------------------------------------------------------------
# PermissionPolicy — interactive (no confirm callback)
# ---------------------------------------------------------------------------

def test_policy_interactive_asks_network_command() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy(interactive=True)
    decision = policy.decide_command("curl https://example.com")
    assert decision.requires_approval is True
    assert decision.action == "ask"
    assert decision.reason == "network_command"


def test_policy_interactive_asks_shell_control() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy(interactive=True)
    decision = policy.decide_command("cat file.txt | grep hello")
    assert decision.requires_approval is True
    assert decision.action == "ask"


def test_policy_interactive_asks_risky_git() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy(interactive=True)
    decision = policy.decide_command("git checkout -b feature")
    assert decision.requires_approval is True
    assert decision.reason == "risky_git_command"


def test_policy_interactive_still_denies_destructive() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy(interactive=True)
    decision = policy.decide_command("rm -rf /")
    assert decision.denied is True
    assert decision.reason == "destructive_command"


def test_policy_interactive_allows_safe() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy(interactive=True)
    decision = policy.decide_command("python -c 'print(1)'")
    assert decision.allowed is True


# ---------------------------------------------------------------------------
# PermissionPolicy — confirm callback
# ---------------------------------------------------------------------------

def test_policy_confirm_callback_approved() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    def auto_approve(_decision):
        return True

    policy = PermissionPolicy(confirm=auto_approve)
    decision = policy.decide_command("curl https://example.com")
    assert decision.allowed is True


def test_policy_confirm_callback_denied() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    def auto_deny(_decision):
        return False

    policy = PermissionPolicy(confirm=auto_deny)
    decision = policy.decide_command("curl https://example.com")
    assert decision.denied is True


def test_policy_confirm_callback_does_not_override_destructive() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    def auto_approve(_decision):
        return True

    policy = PermissionPolicy(confirm=auto_approve)
    decision = policy.decide_command("sudo rm -rf /")
    assert decision.denied is True
    assert decision.reason == "destructive_command"


# ---------------------------------------------------------------------------
# PermissionPolicy — session authorization (category)
# ---------------------------------------------------------------------------

def test_policy_category_auth_skips_interactive_for_network() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy(interactive=True)
    policy.authorize("category", "network")
    decision = policy.decide_command("curl https://example.com")
    assert decision.allowed is True


def test_policy_category_auth_shell_control() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy(interactive=True)
    policy.authorize("category", "shell_control")
    decision = policy.decide_command("echo a | grep a")
    assert decision.allowed is True


def test_policy_category_auth_risky_git() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy(interactive=True)
    policy.authorize("category", "risky_git")
    decision = policy.decide_command("git checkout main")
    assert decision.allowed is True
    assert decision.reason == "safe_risky_git_authorized"


def test_policy_revoke_category_auth() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy(interactive=True)
    policy.authorize("category", "network")
    policy.revoke("category", "network")
    decision = policy.decide_command("curl https://example.com")
    assert decision.requires_approval is True


# ---------------------------------------------------------------------------
# PermissionPolicy — session authorization (prefix)
# ---------------------------------------------------------------------------

def test_policy_prefix_auth_allows_matching_command() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    policy.authorize("prefix", "npm run build")
    decision = policy.decide_command("npm run build --watch")
    assert decision.allowed is True
    assert decision.reason == "safe_command_authorized"


def test_policy_prefix_auth_once_scope() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    policy.authorize("prefix", "pip install", scope="once")

    first = policy.decide_command("pip install requests")
    assert first.allowed is True

    # "once" auth is consumed; second call falls through to classification
    # "pip install pytest" is a network_command (package install), denied in non-interactive mode
    second = policy.decide_command("pip install pytest")
    assert second.denied is True
    assert second.reason == "network_command"


def test_policy_prefix_auth_no_match() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    policy.authorize("prefix", "npm run dev")

    # "curl" is a network command, prefix auth doesn't match → denied
    decision = policy.decide_command("curl https://example.com")
    assert decision.denied is True


# ---------------------------------------------------------------------------
# PermissionPolicy — audit integration
# ---------------------------------------------------------------------------

def test_policy_audit_logs_every_decision() -> None:
    from hermes_lite.coding.audit import AuditLogger
    from hermes_lite.coding.permissions import PermissionPolicy

    logger = AuditLogger()
    policy = PermissionPolicy(audit=logger)

    policy.decide_command("ls")
    policy.decide_command("rm -rf /")
    policy.decide_command("echo hi")

    assert len(logger.entries()) == 3


# ---------------------------------------------------------------------------
# PermissionPolicy — summary
# ---------------------------------------------------------------------------

def test_policy_summary_non_interactive() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    s = policy.summary()
    assert s["mode"] == "auto"
    assert s["interactive"] is False
    assert "destructive_commands" in s
    assert "authorizations" in s
    assert "audit" in s


def test_policy_summary_interactive() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy(interactive=True)
    s = policy.summary()
    assert s["interactive"] is True


# ---------------------------------------------------------------------------
# PermissionPolicy — edge cases
# ---------------------------------------------------------------------------

def test_policy_empty_command() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    decision = policy.decide_command("")
    assert decision.denied is True
    assert decision.reason == "empty_command"


def test_policy_command_with_npm_run() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    # npm run is NOT npm install — should be allowed
    decision = policy.decide_command("npm run test")
    assert decision.allowed is True


def test_policy_npm_install_is_denied_non_interactive() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    decision = policy.decide_command("npm install express")
    assert decision.denied is True


def test_policy_yarn_add_is_denied_non_interactive() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    decision = policy.decide_command("yarn add react")
    assert decision.denied is True


def test_policy_cargo_install_is_denied_non_interactive() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy

    policy = PermissionPolicy()
    decision = policy.decide_command("cargo install ripgrep")
    assert decision.denied is True
