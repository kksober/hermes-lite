"""Conservative permission decisions for coding-agent operations."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from hermes_lite.coding.workspace import PathCheck

DecisionAction = Literal["allow", "ask", "deny"]


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

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready representation."""
        return {
            "action": self.action,
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "operation": self.operation,
            "target": self.target,
            "reason": self.reason,
            "message": self.message,
        }


class PermissionPolicy:
    """Non-interactive permission policy for company-safe coding mode."""

    destructive_commands = {
        "rm",
        "rmdir",
        "sudo",
        "su",
        "chmod",
        "chown",
        "dd",
        "mkfs",
        "shutdown",
        "reboot",
        "kill",
        "pkill",
        "killall",
    }
    network_commands = {"curl", "wget", "ssh", "scp", "sftp", "ftp", "nc", "netcat"}
    shell_control_operators = {"&&", "||", ";", "|", ">", "<"}
    risky_git_subcommands = {"clean", "reset", "checkout", "switch", "restore"}

    def __init__(self, mode: str = "auto") -> None:
        self.mode = mode

    def allow(self, operation: str, target: str, reason: str) -> PermissionDecision:
        return PermissionDecision("allow", operation, target, reason)

    def deny(
        self,
        operation: str,
        target: str,
        reason: str,
        message: str = "",
    ) -> PermissionDecision:
        return PermissionDecision("deny", operation, target, reason, message)

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

    def decide_command(self, command: str) -> PermissionDecision:
        """Decide whether a shell command may run."""
        stripped = command.strip()
        if not stripped:
            return self.deny("command", command, "empty_command", "Command is empty.")
        try:
            args = shlex.split(stripped)
        except ValueError as exc:
            return self.deny("command", command, "invalid_command", str(exc))
        if not args:
            return self.deny("command", command, "empty_command", "Command is empty.")
        if "`" in stripped or "$(" in stripped or any(
            token in self.shell_control_operators for token in args
        ):
            return self.deny(
                "command",
                command,
                "shell_control_operator",
                "Shell control operators are not allowed in phase 1.",
            )

        executable = Path(args[0]).name.lower()
        if executable in self.destructive_commands:
            return self.deny("command", command, "destructive_command")
        if executable in self.network_commands:
            return self.deny("command", command, "network_command")
        if executable == "git" and len(args) > 1 and args[1] in self.risky_git_subcommands:
            return self.deny("command", command, "destructive_git_command")
        if executable in {"pip", "pip3", "npm", "pnpm", "yarn", "uv"} and "install" in args[1:]:
            return self.deny("command", command, "network_command")
        return self.allow("command", command, "safe_command")

    def summary(self) -> dict[str, object]:
        """Return a concise policy summary."""
        return {
            "mode": self.mode,
            "reads": "allow workspace reads except protected paths",
            "writes": "allow workspace writes except protected paths",
            "commands": "deny destructive, network, and shell-control commands",
            "destructive_commands": sorted(self.destructive_commands),
            "network_commands": sorted(self.network_commands),
        }
