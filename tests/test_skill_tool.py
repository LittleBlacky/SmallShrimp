from __future__ import annotations
"""Skill 工具测试。"""
import tempfile
from pathlib import Path
from src.SmallShrimp.core.definitions.skill_loader import SkillLoader
from src.SmallShrimp.tools.skill_tool import create_skill_tool


def test_create_skill_tool():
    """测试创建 skill 工具。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        loader = SkillLoader(Path(tmpdir))
        tool = create_skill_tool(loader)

        assert tool.name == "skill"
        assert "Load a skill" in tool.description
        assert "skill" in tool.description  # 包含 skill 描述


def test_skill_tool_call_not_found():
    """测试加载不存在的 skill。"""
    import asyncio
    with tempfile.TemporaryDirectory() as tmpdir:
        loader = SkillLoader(Path(tmpdir))
        tool = create_skill_tool(loader)

        result = asyncio.run(tool._wrapper(skill_name="nonexistent"))

        # 工具应该返回包含 "not found" 的结果
        assert "not found" in str(result.content).lower() or "not found" in str(result.error).lower()


def test_skill_tool_call_found():
    """测试加载存在的 skill。"""
    import asyncio
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建测试 skill 文件
        skill_dir = Path(tmpdir) / "test-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("""---
id: test-skill
name: test-skill
description: Test skill description
---

# Test Skill Content
This is the skill body.
""")

        loader = SkillLoader(Path(tmpdir))
        tool = create_skill_tool(loader)

        result = asyncio.run(tool._wrapper(skill_name="test-skill"))

        assert result.success
        assert "Test Skill Content" in result.content
        assert "skill body" in result.content


def test_create_skill_tool_description_includes_standard_metadata():
    """工具描述暴露标准 skill 元数据和可选版本状态。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_dir = Path(tmpdir) / "coding-review"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("""---
name: Code Review
description: Review local code changes.
status: active
version: 1.0.0
---

# Code Review
""")

        loader = SkillLoader(Path(tmpdir))
        tool = create_skill_tool(loader)

        assert 'name="Code Review"' in tool.description
        assert 'id="coding-review"' in tool.description
        assert 'version="1.0.0"' in tool.description
        assert 'status="active"' in tool.description


if __name__ == "__main__":
    test_create_skill_tool()
    test_skill_tool_call_not_found()
    test_skill_tool_call_found()
    print("\nAll test_skill_tool tests passed!")
