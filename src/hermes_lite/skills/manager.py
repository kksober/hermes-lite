"""Skill manager — file-based skill system with YAML frontmatter.

Skills are stored as Markdown files: ``skills/<name>/SKILL.md``.
Each file has YAML frontmatter with ``name``, ``description``, and ``version``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse YAML frontmatter from a Markdown string.

    Args:
        text: Full text content potentially starting with ``---`` frontmatter.

    Returns:
        A tuple of ``(frontmatter_dict, body_text)``.  If no frontmatter is
        found the dict will be empty and body will be the full text.
    """
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    frontmatter: dict[str, str] = {}
    for line in parts[1].strip().split("\n"):
        line = line.strip()
        if ":" in line:
            key, value = line.split(":", 1)
            frontmatter[key.strip()] = value.strip()
    return frontmatter, parts[2].strip()


def _make_frontmatter(meta: dict[str, str]) -> str:
    """Serialize a metadata dict back to YAML frontmatter text."""
    lines = ["---"]
    for key, value in meta.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


class SkillManager:
    """Manages skills stored as Markdown files on disk.

    On initialisation the manager scans ``base_dir`` to discover existing
    skills.  Each skill lives in a sub-directory containing a ``SKILL.md``
    file with YAML frontmatter.

    Usage::

        sm = SkillManager(base_dir="skills/")
        print(sm.index())           # compact listing for system prompt
        content = sm.load("my-skill")
        sm.create("new-skill", content_with_frontmatter)
    """

    def __init__(self, base_dir: str = "skills/") -> None:
        """Initialise the skill manager and discover existing skills.

        Args:
            base_dir: Root directory where skill sub-directories are stored.
        """
        self._base_dir = Path(base_dir).resolve()
        self._skills: dict[str, dict[str, Any]] = {}
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._discover()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index(self) -> str:
        """Return a compact name + description listing for system prompt injection.

        Returns:
            A string like::

                <available_skills>
                - web-scraper: Scrape and parse web pages
                - code-review: Review code for best practices
                </available_skills>
        """
        if not self._skills:
            return ""

        lines = ["<available_skills>"]
        for meta in self._skills.values():
            desc = meta.get("description", "")
            lines.append(f"- {meta['name']}: {desc}")
        lines.append("</available_skills>")
        return "\n".join(lines)

    def load(self, name: str) -> str | None:
        """Return the full ``SKILL.md`` content for a skill.

        Args:
            name: Skill directory name.

        Returns:
            Complete markdown text, or ``None`` if not found.
        """
        skill_dir = self._base_dir / name
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            return None
        return skill_file.read_text(encoding="utf-8")

    def create(self, name: str, content: str) -> str:
        """Create (or overwrite) a skill.

        The ``content`` parameter must be the complete ``SKILL.md`` text
        including YAML frontmatter.

        Args:
            name: Skill directory name.
            content: Full ``SKILL.md`` text with frontmatter.

        Returns:
            The skill name (for chaining).

        Raises:
            ValueError: If the content does not have valid frontmatter with a ``name`` key.
        """
        frontmatter, _body = _parse_frontmatter(content)
        if "name" not in frontmatter:
            raise ValueError(
                "Skill content must have YAML frontmatter with a 'name' field"
            )

        skill_dir = self._base_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(content, encoding="utf-8")

        # Update in-memory registry
        self._skills[name] = {
            "name": frontmatter.get("name", name),
            "description": frontmatter.get("description", ""),
            "version": frontmatter.get("version", "0.1.0"),
        }
        return name

    def patch(self, name: str, old_string: str, new_string: str) -> bool:
        """Replace a text fragment inside a skill's ``SKILL.md``.

        Args:
            name: Skill directory name.
            old_string: Exact text to find and replace.
            new_string: Replacement text.

        Returns:
            ``True`` if a match was found and replaced, ``False`` otherwise.
        """
        content = self.load(name)
        if content is None:
            return False
        if old_string not in content:
            return False
        updated = content.replace(old_string, new_string, 1)
        skill_file = self._base_dir / name / "SKILL.md"
        skill_file.write_text(updated, encoding="utf-8")
        return True

    def delete(self, name: str) -> bool:
        """Delete a skill directory and all its contents.

        Args:
            name: Skill directory name.

        Returns:
            ``True`` if the skill existed and was deleted, ``False`` otherwise.
        """
        skill_dir = self._base_dir / name
        if not skill_dir.is_dir():
            return False
        import shutil

        shutil.rmtree(skill_dir)
        self._skills.pop(name, None)
        return True

    def list_all(self) -> list[dict[str, Any]]:
        """Return metadata for all installed skills.

        Returns:
            List of dicts with ``name``, ``description``, ``version`` keys.
        """
        return list(self._skills.values())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _discover(self) -> None:
        """Scan ``base_dir`` and register all valid skill directories."""
        if not self._base_dir.is_dir():
            return

        for entry in sorted(self._base_dir.iterdir()):
            if not entry.is_dir():
                continue
            skill_file = entry / "SKILL.md"
            if not skill_file.is_file():
                continue
            try:
                text = skill_file.read_text(encoding="utf-8")
                frontmatter, _body = _parse_frontmatter(text)
                name = frontmatter.get("name", entry.name)
                self._skills[entry.name] = {
                    "name": name,
                    "description": frontmatter.get("description", ""),
                    "version": frontmatter.get("version", "0.1.0"),
                }
            except Exception:
                # Silently skip malformed skills
                continue
