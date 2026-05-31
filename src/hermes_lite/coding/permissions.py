"""Conservative permission decisions for coding-agent operations.

Supports three decision actions:
- ``allow``: proceed without confirmation
- ``ask``: require user confirmation before proceeding
- ``deny``: block the operation

When a *confirm callback* is provided to the policy, ``ask`` decisions are
escalated to the callback.  Without a callback (e.g. API mode), ``ask``
falls back to ``deny`` — safe by default.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from hermes_lite.coding.audit import AuditLogger
from hermes_lite.coding.workspace import PathCheck

DecisionAction = Literal["allow", "ask", "deny"]
ConfirmCallback = Callable[["PermissionDecision"], bool]


@dataclass(frozen=True)
class PermissionDecision:
    """A structured allow/ask/deny decision."""

    action: DecisionAction
    operation: str
    target: str
    reason: str
    message: str = ""

    @property
    def allowed(self) -> bool:
        """Return whether the operation may proceed without approval."""
        return self.action == "allow"

    @property
    def requires_approval(self) -> bool:
        """Return whether an interactive UI should ask the user."""
        return self.action == "ask"

    @property
    def denied(self) -> bool:
        """Return whether the operation is blocked."""
        return self.action == "deny"

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready representation."""
        return {
            "action": self.action,
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "denied": self.denied,
            "operation": self.operation,
            "target": self.target,
            "reason": self.reason,
            "message": self.message,
        }


@dataclass
class SessionAuthorization:
    """A temporary authorization scoped to a command prefix, path, or category."""

    kind: Literal["prefix", "path", "category"]
    value: str
    scope: Literal["once", "session"] = "session"
    used: bool = False


class PermissionPolicy:
    """Interactive-capable permission policy for company-safe coding mode.

    Parameters
    ----------
    mode:
        Policy mode label (``"auto"``, ``"strict"``, etc.).
    interactive:
        When ``True``, borderline commands return ``ask`` instead of ``deny``.
    confirm:
        Optional callback invoked for ``ask`` decisions.  Return ``True`` to
        approve, ``False`` to deny.  If not set, ``ask`` is treated as ``deny``.
    audit:
        Optional :class:`AuditLogger` for recording every decision.
    """

    destructive_commands = {
        "rm", "rmdir", "sudo", "su", "chmod", "chown",
        "dd", "mkfs", "shutdown", "reboot",
        "kill", "pkill", "killall",
    }
    network_commands = {
        "curl", "wget", "ssh", "scp", "sftp", "ftp", "nc", "netcat",
    }
    shell_control_operators = {"&&", "||", ";", "|", ">", "<"}
    risky_git_subcommands = {"clean", "reset", "checkout", "switch", "restore"}
    package_managers = {"pip", "pip3", "npm", "pnpm", "yarn", "uv", "cargo", "go", "gem", "brew"}
    package_install_subcommands = {"install", "add", "i", "global"}

    def __init__(
        self,
        mode: str = "auto",
        interactive: bool = False,
        confirm: ConfirmCallback | None = None,
        audit: AuditLogger | None = None,
        *,
        ask_timeout: float = 60.0,
        headless_webhook: str = "",
    ) -> None:
        self.mode = mode
        self.interactive = interactive
        self.confirm = confirm
        self.audit = audit or AuditLogger()
        self._authorizations: list[SessionAuthorization] = []
        self.ask_timeout = ask_timeout
        self.headless_webhook = headless_webhook

    # ------------------------------------------------------------------
    # session authorizations
    # ------------------------------------------------------------------

    def authorize(
        self,
        kind: Literal["prefix", "path", "category"],
        value: str,
        scope: Literal["once", "session"] = "session",
    ) -> None:
        """Grant a temporary session-level authorization."""
        self._authorizations.append(SessionAuthorization(kind=kind, value=value, scope=scope))

    def revoke(self, kind: str, value: str) -> None:
        """Remove matching authorizations."""
        self._authorizations = [
            a for a in self._authorizations
            if not (a.kind == kind and a.value == value)
        ]

    def list_authorizations(self) -> list[dict[str, object]]:
        """Return active authorizations as dicts."""
        return [
            {"kind": a.kind, "value": a.value, "scope": a.scope, "used": a.used}
            for a in self._authorizations
        ]

    def _check_session_auth(self, command: str) -> bool:
        """Return True if any session authorization matches the command."""
        for auth in self._authorizations:
            if auth.used and auth.scope == "once":
                continue
            if auth.kind == "prefix" and command.startswith(auth.value):
                auth.used = True
                return True
            if auth.kind == "category":
                # Category match checked in decide_command based on classification
                pass
        return False

    def _has_category_auth(self, category: str) -> bool:
        """Check if a category-level authorization exists."""
        for auth in self._authorizations:
            if auth.used and auth.scope == "once":
                continue
            if auth.kind == "category" and auth.value == category:
                return True
        return False

    # ------------------------------------------------------------------
    # decision helpers
    # ------------------------------------------------------------------

    def allow(self, operation: str, target: str, reason: str) -> PermissionDecision:
        d = PermissionDecision("allow", operation, target, reason)
        self.audit.record("permission", operation, target, "allow", reason)
        return d

    def ask_decision(
        self, operation: str, target: str, reason: str, message: str = ""
    ) -> PermissionDecision:
        """Return an ``ask`` decision, checking callback if provided."""
        if self.confirm is not None:
            d = PermissionDecision("ask", operation, target, reason, message)
            self.audit.record("permission", operation, target, "ask", reason)
            approved = self.confirm(d)
            if approved:
                self.audit.record("permission_confirmed", operation, target, "allow", reason)
                return PermissionDecision("allow", operation, target, reason)
            else:
                self.audit.record("permission_denied", operation, target, "deny", reason)
                return PermissionDecision("deny", operation, target, reason, f"User denied: {message}")
        elif self.interactive:
            self.audit.record("permission", operation, target, "ask", reason)
            return PermissionDecision("ask", operation, target, reason, message)
        else:
            self.audit.record("permission", operation, target, "deny", reason)
            return PermissionDecision("deny", operation, target, reason, message)

    def deny(
        self, operation: str, target: str, reason: str, message: str = ""
    ) -> PermissionDecision:
        d = PermissionDecision("deny", operation, target, reason, message)
        self.audit.record("permission", operation, target, "deny", reason)
        return d

    # ------------------------------------------------------------------
    # path decisions
    # ------------------------------------------------------------------

    def decide_read(self, check: PathCheck) -> PermissionDecision:
        """Decide whether a file read may proceed."""
        if not check.ok:
            return self.deny("read", check.relative_path or str(check.path), check.error, check.reason)
        return self.allow("read", check.relative_path, "safe_read")

    def decide_write(self, check: PathCheck) -> PermissionDecision:
        """Decide whether a file write may proceed."""
        if not check.ok:
            return self.deny("write", check.relative_path or str(check.path), check.error, check.reason)
        return self.allow("write", check.relative_path, "workspace_write")

    # ------------------------------------------------------------------
    # command decisions
    # ------------------------------------------------------------------

    def _classify_command(self, args: list[str]) -> tuple[str, str] | None:
        """Classify a parsed command.  Returns ``(category, detail)`` or ``None``."""
        if not args:
            return None
        executable = Path(args[0]).name.lower()

        if executable in self.destructive_commands:
            return ("destructive", executable)
        if executable in self.network_commands:
            return ("network", executable)
        if executable in self.package_managers:
            subcommands = set(args[1:]) if len(args) > 1 else set()
            if subcommands & self.package_install_subcommands:
                return ("network", f"{executable} install")
        if executable == "git" and len(args) > 1 and args[1] in self.risky_git_subcommands:
            return ("risky_git", f"git {args[1]}")
        return None

    def decide_command(self, command: str) -> PermissionDecision:
        """Decide whether a shell command may run.

        Decision tiers (in order):
        1.  Empty / unparseable commands are **denied**.
        2.  Shell control operators — **ask** (interactive) or **deny**.
        3.  Destructive commands (rm, sudo, etc.) — always **deny**.
        4.  Network / package-install / risky-git — **ask** when interactive,
            **deny** otherwise; skipped if session-authorized.
        5.  Session prefix authorizations — **allow**.
        6.  Everything else — **allow**.
        """
        stripped = command.strip()
        if not stripped:
            return self.deny("command", command, "empty_command", "Command is empty.")

        try:
            args = shlex.split(stripped)
        except ValueError as exc:
            return self.deny("command", command, "invalid_command", str(exc))

        if not args:
            return self.deny("command", command, "empty_command", "Command is empty.")

        # Tier 2: shell control operators
        if "`" in stripped or "$(" in stripped:
            return self.deny(
                "command", command, "command_substitution",
                "Command substitution is not allowed."
            )
        if any(token in self.shell_control_operators for token in args):
            if self._has_category_auth("shell_control"):
                return self.allow("command", command, "safe_command_authorized")
            return self.ask_decision(
                "command", command, "shell_control_operator",
                "Shell control operators (|, &&, ||, etc.) require confirmation.",
            )

        # Tier 3: destructive commands
        executable = Path(args[0]).name.lower()
        if executable in self.destructive_commands:
            return self.deny("command", command, "destructive_command")

        # Tier 4: session prefix authorization
        if self._check_session_auth(command):
            return self.allow("command", command, "safe_command_authorized")

        # Tier 5: borderline commands (network / package install / risky git)
        classification = self._classify_command(args)
        if classification:
            category, detail = classification
            if self._has_category_auth(category):
                return self.allow("command", command, f"safe_{category}_authorized")
            if self.interactive or self.confirm:
                return self.ask_decision(
                    "command", command, f"{category}_command",
                    f"The command '{detail}' requires confirmation (category: {category}).",
                )
            return self.deny("command", command, f"{category}_command")

        # Tier 6: safe command
        return self.allow("command", command, "safe_command")

    # ------------------------------------------------------------------
    # summary
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, object]:
        """Return a concise policy summary."""
        return {
            "mode": self.mode,
            "interactive": self.interactive,
            "ask_timeout": self.ask_timeout,
            "headless": bool(self.headless_webhook),
            "reads": "allow workspace reads except protected paths",
            "writes": "allow workspace writes except protected paths",
            "commands": self._command_summary_desc(),
            "destructive_commands": sorted(self.destructive_commands),
            "network_commands": sorted(self.network_commands),
            "authorizations": self.list_authorizations(),
            "audit": self.audit.summary(),
        }

    def _command_summary_desc(self) -> str:
        if self.interactive or self.confirm:
            return (
                "deny destructive; ask network/package/git-risky/shell-control; "
                "allow safe"
            )
        return "deny destructive, network, shell-control, and package-install commands"
