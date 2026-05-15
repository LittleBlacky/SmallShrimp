"""Tools package - 统一工具注册入口"""
from .registry import ToolRegistry
from .decorators import tool


def create_tool_registry(config: dict) -> ToolRegistry:
    """根据配置创建工具注册表"""
    registry = ToolRegistry()

    # 内置工具（零配置）
    from .builtin_tools import read, write, glob, grep
    registry.register(read)
    registry.register(write)
    registry.register(glob)
    registry.register(grep)

    # Skill 工具
    skills_dir = config.get("skills_dir", "workspace/skills")
    from pathlib import Path
    from .skill_tool import create_skill_tool
    from ..core.skill_loader import SkillLoader
    skill_loader = SkillLoader(Path(skills_dir))
    registry.register(create_skill_tool(skill_loader))

    # Web 工具（有配置才注册）
    if config.get("websearch"):
        from .web_tools import create_websearch_tool
        registry.register(create_websearch_tool(config["websearch"]))

    if config.get("webread"):
        from .web_tools import create_webread_tool
        registry.register(create_webread_tool())

    return registry