"""Coding-agent prompt fragment."""

from __future__ import annotations

from hermes_lite.coding.permissions import PermissionPolicy
from hermes_lite.coding.workspace import Workspace

CODING_AGENT_PROMPT = """\
You are operating as a coding agent inside a local workspace.

Follow this workflow:
- Inspect the project before editing.
- Prefer search and small file reads over broad guessing.
- Preserve unrelated user changes.
- Use patch-oriented edits for existing files.
- Keep changes focused and reversible.
- Run focused verification after edits.
- Summarize changed files and verification evidence.
- Do not claim code works without fresh verification output.

Safety rules:
- Treat the workspace root as the boundary for writes and commands.
- Do not write protected files such as .env, .git, private keys, dependency caches, or virtualenvs.
- Do not run destructive, network, or shell-control commands.
- When a tool reports a structured error, recover by inspecting context or asking the user.
"""


def build_coding_prompt(workspace: Workspace, permission_policy: PermissionPolicy) -> str:
    """Build a workspace-specific coding prompt fragment."""
    summary = workspace.summary()
    permissions = permission_policy.summary()
    return (
        CODING_AGENT_PROMPT
        + "\n<workspace>\n"
        + f"root: {summary['root']}\n"
        + f"is_git_repo: {summary['is_git_repo']}\n"
        + "</workspace>\n"
        + "<permission_policy>\n"
        + f"mode: {permissions['mode']}\n"
        + f"commands: {permissions['commands']}\n"
        + "</permission_policy>"
    )
