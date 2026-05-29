"""Git helpers for coding-agent workflows."""

from __future__ import annotations

import shutil
import subprocess

from hermes_lite.coding.workspace import Workspace


class GitClient:
    """Small git wrapper scoped to a workspace."""

    def __init__(self, workspace: Workspace, timeout_seconds: float = 10.0) -> None:
        self.workspace = workspace
        self.timeout_seconds = timeout_seconds

    def is_git_repo(self) -> bool:
        """Return whether the workspace is inside a git work tree."""
        if shutil.which("git") is None:
            return False
        result = self._run(["rev-parse", "--is-inside-work-tree"])
        return result["exit_code"] == 0 and str(result["stdout"]).strip() == "true"

    def status(self) -> dict[str, object]:
        """Return git branch and short status."""
        if shutil.which("git") is None:
            return {"ok": False, "error": "git_not_found"}
        if not self.is_git_repo():
            return {"ok": False, "error": "not_git_repo", "short": ""}
        branch = self._run(["branch", "--show-current"])
        status = self._run(["status", "--short"])
        short = str(status["stdout"])
        return {
            "ok": status["exit_code"] == 0,
            "branch": str(branch["stdout"]).strip(),
            "short": short,
            "clean": short.strip() == "",
            "stderr": status["stderr"],
        }

    def diff(self, path: str = "", *, stat: bool = False, max_output_chars: int = 20_000) -> dict[str, object]:
        """Return git diff output."""
        if shutil.which("git") is None:
            return {"ok": False, "error": "git_not_found", "diff": ""}
        if not self.is_git_repo():
            return {"ok": False, "error": "not_git_repo", "diff": ""}
        args = ["diff"]
        if stat:
            args.append("--stat")
        if path:
            args.extend(["--", path])
        result = self._run(args)
        diff_text = str(result["stdout"])
        truncated = len(diff_text) > max_output_chars
        if truncated:
            diff_text = diff_text[:max_output_chars]
        return {
            "ok": result["exit_code"] == 0,
            "diff": diff_text,
            "stderr": result["stderr"],
            "truncated": truncated,
        }

    def worktree_status(self) -> dict[str, object]:
        """Return worktree information without creating or mutating worktrees."""
        if shutil.which("git") is None:
            return {"ok": False, "error": "git_not_found", "is_git_repo": False, "worktrees": []}
        if not self.is_git_repo():
            return {"ok": True, "is_git_repo": False, "worktrees": []}
        git_dir = self._run(["rev-parse", "--git-dir"])
        common_dir = self._run(["rev-parse", "--git-common-dir"])
        listing = self._run(["worktree", "list", "--porcelain"])
        return {
            "ok": listing["exit_code"] == 0,
            "is_git_repo": True,
            "git_dir": str(git_dir["stdout"]).strip(),
            "git_common_dir": str(common_dir["stdout"]).strip(),
            "is_linked_worktree": str(git_dir["stdout"]).strip() != str(common_dir["stdout"]).strip(),
            "worktrees": self._parse_worktree_list(str(listing["stdout"])),
        }

    def _run(self, args: list[str]) -> dict[str, object]:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.workspace.root,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return {"exit_code": 1, "stdout": "", "stderr": str(exc)}
        return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}

    def _parse_worktree_list(self, text: str) -> list[dict[str, str]]:
        worktrees: list[dict[str, str]] = []
        current: dict[str, str] = {}
        for line in text.splitlines():
            if not line:
                if current:
                    worktrees.append(current)
                    current = {}
                continue
            if " " in line:
                key, value = line.split(" ", 1)
            else:
                key, value = line, ""
            current[key] = value
        if current:
            worktrees.append(current)
        return worktrees
