"""Tests for the skills system."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


SKILL_MD_TEMPLATE = """---
name: Web Scraper
description: Scrape and parse web pages
version: 1.0.0
---

# Web Scraper Skill

This skill enables web scraping using BeautifulSoup.
"""


class TestSkillManager:
    """Test SkillManager — create, load, patch, delete, discover."""

    def test_create_and_load(self) -> None:
        """Test creating a skill and loading its content."""
        from hermes_lite.skills import SkillManager

        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SkillManager(base_dir=tmpdir)
            sm.create("web-scraper", SKILL_MD_TEMPLATE)

            content = sm.load("web-scraper")
            assert content is not None
            assert "Web Scraper" in content
            assert "BeautifulSoup" in content

    def test_load_missing(self) -> None:
        """Test loading a non-existent skill returns None."""
        from hermes_lite.skills import SkillManager

        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SkillManager(base_dir=tmpdir)
            assert sm.load("nonexistent") is None

    def test_index(self) -> None:
        """Test that index() returns a compact listing."""
        from hermes_lite.skills import SkillManager

        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SkillManager(base_dir=tmpdir)
            sm.create("web-scraper", SKILL_MD_TEMPLATE)

            content_2 = """---
name: Code Review
description: Review code for best practices
version: 0.2.0
---

# Code Review Skill
"""
            sm.create("code-review", content_2)

            idx = sm.index()
            assert "<available_skills>" in idx
            assert "Web Scraper" in idx
            assert "Code Review" in idx
            assert "Scrape and parse" in idx

    def test_index_empty(self) -> None:
        """Test that index() returns an empty string when no skills exist."""
        from hermes_lite.skills import SkillManager

        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SkillManager(base_dir=tmpdir)
            assert sm.index() == ""

    def test_list_all(self) -> None:
        """Test listing all skill metadata."""
        from hermes_lite.skills import SkillManager

        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SkillManager(base_dir=tmpdir)
            sm.create("web-scraper", SKILL_MD_TEMPLATE)

            all_skills = sm.list_all()
            assert len(all_skills) == 1
            assert all_skills[0]["name"] == "Web Scraper"
            assert all_skills[0]["description"] == "Scrape and parse web pages"
            assert all_skills[0]["version"] == "1.0.0"

    def test_patch(self) -> None:
        """Test patching a skill's content."""
        from hermes_lite.skills import SkillManager

        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SkillManager(base_dir=tmpdir)
            sm.create("web-scraper", SKILL_MD_TEMPLATE)

            result = sm.patch("web-scraper", "BeautifulSoup", "Scrapy")
            assert result is True

            content = sm.load("web-scraper")
            assert content is not None
            assert "Scrapy" in content
            assert "BeautifulSoup" not in content

    def test_patch_no_match(self) -> None:
        """Test patching a non-existent string returns False."""
        from hermes_lite.skills import SkillManager

        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SkillManager(base_dir=tmpdir)
            sm.create("web-scraper", SKILL_MD_TEMPLATE)

            result = sm.patch("web-scraper", "zzz_nonexistent_zzz", "replacement")
            assert result is False

    def test_patch_missing_skill(self) -> None:
        """Test patching a non-existent skill returns False."""
        from hermes_lite.skills import SkillManager

        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SkillManager(base_dir=tmpdir)
            assert sm.patch("nonexistent", "a", "b") is False

    def test_delete(self) -> None:
        """Test deleting a skill."""
        from hermes_lite.skills import SkillManager

        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SkillManager(base_dir=tmpdir)
            sm.create("web-scraper", SKILL_MD_TEMPLATE)
            assert sm.load("web-scraper") is not None

            result = sm.delete("web-scraper")
            assert result is True
            assert sm.load("web-scraper") is None
            assert sm.list_all() == []

    def test_delete_missing(self) -> None:
        """Test deleting a non-existent skill returns False."""
        from hermes_lite.skills import SkillManager

        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SkillManager(base_dir=tmpdir)
            assert sm.delete("nonexistent") is False

    def test_create_no_frontmatter(self) -> None:
        """Test that creating a skill without frontmatter raises ValueError."""
        from hermes_lite.skills import SkillManager

        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SkillManager(base_dir=tmpdir)
            with pytest.raises(ValueError, match="frontmatter"):
                sm.create("bad", "# No frontmatter here")

    def test_auto_discover(self) -> None:
        """Test that existing skills are discovered on init."""
        from hermes_lite.skills import SkillManager

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            # Create a skill manually on disk
            skill_dir = base / "existing-skill"
            skill_dir.mkdir()
            skill_file = skill_dir / "SKILL.md"
            skill_file.write_text(SKILL_MD_TEMPLATE, encoding="utf-8")

            # Initialise manager — should pick up the existing skill
            sm = SkillManager(base_dir=str(base))
            all_skills = sm.list_all()
            assert len(all_skills) == 1
            assert all_skills[0]["name"] == "Web Scraper"

            # Can still load it
            content = sm.load("existing-skill")
            assert content is not None
            assert "BeautifulSoup" in content

    def test_create_overwrite(self) -> None:
        """Test that creating with the same name overwrites the skill."""
        from hermes_lite.skills import SkillManager

        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SkillManager(base_dir=tmpdir)
            sm.create("test-skill", SKILL_MD_TEMPLATE)

            new_content = """---
name: Updated Skill
description: Updated description
version: 2.0.0
---

# Updated
"""
            sm.create("test-skill", new_content)

            content = sm.load("test-skill")
            assert content is not None
            assert "Updated" in content
            assert "BeautifulSoup" not in content

            meta = sm.list_all()
            assert meta[0]["name"] == "Updated Skill"
