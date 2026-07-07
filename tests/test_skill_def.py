from __future__ import annotations
"""Skill 定义测试。"""
import tempfile
from pathlib import Path
from src.SmallShrimp.core.definitions.skill_def import SkillDef


def test_skill_def_from_file():
    """测试从文件加载 SkillDef。"""
    content = """---
id: test-skill
name: Test Skill
description: A test skill for unit testing
---

# Test Skill

This is a test skill.
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_file = Path(tmpdir) / "SKILL.md"
        skill_file.write_text(content)

        skill = SkillDef.from_file(skill_file)
        assert skill.id == "test-skill"
        assert skill.name == "Test Skill"
        assert skill.description == "A test skill for unit testing"
        assert "Test Skill" in skill.content
        assert "This is a test skill" in skill.content


def test_skill_def_to_dict():
    """测试 SkillDef 转换为字典。"""
    skill = SkillDef(
        id="my-skill",
        name="My Skill",
        description="Description of my skill",
        content="# My Skill\n\nContent here."
    )
    data = skill.to_dict()
    assert data["id"] == "my-skill"
    assert data["name"] == "My Skill"
    assert data["description"] == "Description of my skill"
    assert "Content here" in data["content"]


def test_skill_def_minimal():
    """测试最小化 SkillDef。"""
    skill = SkillDef(
        id="minimal",
        name="Minimal",
        description="Minimal skill"
    )
    assert skill.content == ""


def test_skill_def_missing_frontmatter():
    """测试无 frontmatter 的文件。"""
    content = "# Just Content\n\nNo frontmatter."
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_file = Path(tmpdir) / "SKILL.md"
        skill_file.write_text(content)

        skill = SkillDef.from_file(skill_file)
        # 无 frontmatter 时，使用纯内容
        assert skill.content == "# Just Content\n\nNo frontmatter."


def test_skill_def_parses_standard_minimum_frontmatter():
    """标准 skill 只要求 name 和 description。"""
    content = """---
name: Code Review
description: Review code changes.
---

# Code Review
"""
    skill = SkillDef._parse(content)

    assert skill.id == ""
    assert skill.name == "Code Review"
    assert skill.description == "Review code changes."
    assert skill.triggers is None
    assert skill.origin == "user"
    assert skill.status == "active"


def test_skill_def_parses_optional_smallshrimp_extensions():
    """测试解析 SmallShrimp 可选扩展字段。"""
    content = """---
id: coding.review
name: Code Review
description: Review code.
scene: coding
origin: learned
status: active
created_by: agent
version: 1.0.0
confidence: 0.9
risk_level: medium
triggers:
  - review
---

# Code Review

Review the change.
"""
    skill = SkillDef._parse(content)

    assert skill.id == "coding.review"
    assert skill.scene == "coding"
    assert skill.origin == "learned"
    assert skill.status == "active"
    assert skill.created_by == "agent"
    assert skill.version == "1.0.0"
    assert skill.confidence == 0.9
    assert skill.risk_level == "medium"
    assert skill.triggers == ["review"]


def test_skill_def_to_dict_includes_optional_extensions_when_present():
    """测试 SkillDef 字典包含可选扩展字段。"""
    skill = SkillDef(
        id="coding.review",
        name="Code Review",
        description="Review code.",
        scene="coding",
        origin="learned",
        status="active",
        created_by="agent",
        version="1.0.0",
        confidence=0.9,
        risk_level="medium",
        triggers=["review"],
    )

    data = skill.to_dict()

    assert data["scene"] == "coding"
    assert data["origin"] == "learned"
    assert data["status"] == "active"
    assert data["version"] == "1.0.0"
    assert data["confidence"] == 0.9
    assert data["risk_level"] == "medium"


if __name__ == "__main__":
    test_skill_def_from_file()
    test_skill_def_to_dict()
    test_skill_def_minimal()
    test_skill_def_missing_frontmatter()
    print("\nAll test_skill_def tests passed!")
