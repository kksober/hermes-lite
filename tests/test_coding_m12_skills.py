"""Tests for M12 P2: skill_view and skill_manage tools."""
from __future__ import annotations


def test_skill_view_loads_existing_skill(tmp_path) -> None:
    from hermes_lite.skills.manager import SkillManager

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_dir = skills_dir / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: Test skill\nversion: 1.0.0\n---\n\n# My Skill\n\nDo stuff.\n"
    )

    sm = SkillManager(base_dir=str(skills_dir))
    content = sm.load("my-skill")
    assert content is not None
    assert "# My Skill" in content


def test_skill_view_not_found(tmp_path) -> None:
    from hermes_lite.skills.manager import SkillManager

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    sm = SkillManager(base_dir=str(skills_dir))
    assert sm.load("nonexistent") is None


def test_skill_manage_create(tmp_path) -> None:
    from hermes_lite.skills.manager import SkillManager

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    sm = SkillManager(base_dir=str(skills_dir))

    content = "---\nname: new-skill\ndescription: Created via test\nversion: 0.1.0\n---\n\n# New Skill\n\nContent here.\n"
    name = sm.create("new-skill", content)
    assert name == "new-skill"
    assert (skills_dir / "new-skill" / "SKILL.md").exists()

    loaded = sm.load("new-skill")
    assert "Content here" in (loaded or "")

    skills = sm.list_all()
    assert any(s["name"] == "new-skill" for s in skills)


def test_skill_manage_create_invalid_frontmatter(tmp_path) -> None:
    from hermes_lite.skills.manager import SkillManager
    import pytest

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    sm = SkillManager(base_dir=str(skills_dir))

    with pytest.raises(ValueError, match="YAML frontmatter"):
        sm.create("bad-skill", "# No frontmatter here")


def test_skill_manage_patch(tmp_path) -> None:
    from hermes_lite.skills.manager import SkillManager

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    sm = SkillManager(base_dir=str(skills_dir))

    content = "---\nname: patchy\ndescription: Patch test\nversion: 0.1.0\n---\n\n# Original\n\nOld text.\n"
    sm.create("patchy", content)

    ok = sm.patch("patchy", "Old text", "New text")
    assert ok is True

    loaded = sm.load("patchy")
    assert "New text" in (loaded or "")
    assert "Old text" not in (loaded or "")


def test_skill_manage_delete(tmp_path) -> None:
    from hermes_lite.skills.manager import SkillManager

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    sm = SkillManager(base_dir=str(skills_dir))

    content = "---\nname: temp-skill\ndescription: To be deleted\nversion: 0.1.0\n---\n\n# Temp\n"
    sm.create("temp-skill", content)

    ok = sm.delete("temp-skill")
    assert ok is True
    assert sm.load("temp-skill") is None
    assert not (skills_dir / "temp-skill").exists()

    # Deleting non-existent returns False
    assert sm.delete("nonexistent") is False
