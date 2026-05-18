from __future__ import annotations
"""Skill 加载器测试。"""
import tempfile
from pathlib import Path
from src.SmallShrimp.core.skill_loader import SkillLoader
from src.SmallShrimp.core.skill_def import SkillDef


def create_skill_dir(parent: Path, name: str, content: str) -> Path:
    """创建测试用 skill 目录和文件。"""
    skill_dir = parent / name
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content)
    return skill_dir


def test_skill_loader_discover():
    """测试发现技能。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir)

        # 创建技能目录
        create_skill_dir(skills_dir, "skill-one", """---
id: skill-one
name: Skill One
description: First skill
---

# Skill One
""")
        create_skill_dir(skills_dir, "skill-two", """---
id: skill-two
name: Skill Two
description: Second skill
---

# Skill Two
""")

        loader = SkillLoader(skills_dir)
        skills = loader.discover_skills()

        assert len(skills) == 2
        skill_ids = {s.id for s in skills}
        assert "skill-one" in skill_ids
        assert "skill-two" in skill_ids


def test_skill_loader_discover_empty():
    """测试空目录发现。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        loader = SkillLoader(Path(tmpdir))
        skills = loader.discover_skills()
        assert len(skills) == 0


def test_skill_loader_discover_no_skills_dir():
    """测试不存在的目录。"""
    loader = SkillLoader(Path("/nonexistent/path"))
    skills = loader.discover_skills()
    assert len(skills) == 0


def test_skill_loader_load():
    """测试加载单个技能。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir)
        create_skill_dir(skills_dir, "my-skill", """---
id: my-skill
name: My Skill
description: My test skill
---

# My Skill Content
""")
        loader = SkillLoader(skills_dir)
        skill = loader.load("my-skill")

        assert skill.id == "my-skill"
        assert skill.name == "My Skill"
        assert "My Skill Content" in skill.content


def test_skill_loader_load_not_found():
    """测试加载不存在的技能。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        loader = SkillLoader(Path(tmpdir))
        try:
            loader.load("nonexistent")
            assert False, "Should raise FileNotFoundError"
        except FileNotFoundError:
            pass


def test_skill_loader_list():
    """测试列出所有技能名称。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir)
        create_skill_dir(skills_dir, "alpha", "---\nid: alpha\n---\n")
        create_skill_dir(skills_dir, "beta", "---\nid: beta\n---\n")
        create_skill_dir(skills_dir, "gamma", "---\nid: gamma\n---\n")

        loader = SkillLoader(skills_dir)
        names = loader.list_skills()

        assert len(names) == 3
        assert "alpha" in names
        assert "beta" in names
        assert "gamma" in names


def test_skill_loader_ignores_files():
    """测试忽略非目录文件。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir)
        (skills_dir / "not-a-skill.txt").write_text("not a skill")
        create_skill_dir(skills_dir, "valid-skill", """---
id: valid-skill
name: Valid Skill
description: Valid
---""")

        loader = SkillLoader(skills_dir)
        skills = loader.discover_skills()

        assert len(skills) == 1
        assert skills[0].id == "valid-skill"


if __name__ == "__main__":
    test_skill_loader_discover()
    test_skill_loader_discover_empty()
    test_skill_loader_discover_no_skills_dir()
    test_skill_loader_load()
    test_skill_loader_load_not_found()
    test_skill_loader_list()
    test_skill_loader_ignores_files()
    print("\nAll test_skill_loader tests passed!")
