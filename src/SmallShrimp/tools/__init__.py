"""Tools package - 统一工具注册入口"""
from .registry import ToolRegistry
from .decorators import tool


def create_tool_registry(config: dict) -> ToolRegistry:
    """根据配置创建工具注册表"""
    registry = ToolRegistry()

    # 内置工具（零配置）
    from .builtin_tools import read, write, glob, grep
    from .shell_tool import shell
    registry.register(read)
    registry.register(write)
    registry.register(glob)
    registry.register(grep)
    registry.register(shell)

    # Skill 工具
    skills_dir = config.get("skills_dir", "workspace/skills")
    from pathlib import Path
    from .skill_tool import create_skill_tool
    from ..core.skill_loader import SkillLoader
    skill_loader = SkillLoader(Path(skills_dir))
    registry.register(create_skill_tool(skill_loader))

    # Web 工具（无条件注册，Provider 按配置自动降级）
    from .web_tools import create_websearch_tool, create_webread_tool
    registry.register(create_websearch_tool(config.get("websearch", {})))
    registry.register(create_webread_tool())

    # Cron 工具
    from .cron_tool import create_cron_tool
    registry.register(create_cron_tool())

    return registry


def register_context_tools(registry: ToolRegistry, context) -> None:
    """注册依赖 Context 的工具（需 channels / eventbus / agent_loader）。
    在 Context 创建完成后调用，所有 context 相关工具在此统一注册。
    """
    # post_message：有渠道时注册
    if context.channels:
        from .post_message_tool import create_post_message_tool
        post_tool = create_post_message_tool(context)
        if post_tool:
            registry.register(post_tool)

    # subagent_dispatch：有多个 Agent 时注册
    agents = context.agent_loader.discover_agents()
    if len(agents) > 1:
        from .subagent_tool import create_subagent_dispatch_tool
        agent_id = agents[0].id or agents[0].name
        subagent_tool = create_subagent_dispatch_tool(agent_id, context)
        if subagent_tool:
            registry.register(subagent_tool)

    # 记忆工具：有记忆管理器时注册
    if context.memory_manager is not None:
        from .memory_tool import create_memory_tools
        for t in create_memory_tools(context.memory_manager):
            registry.register(t)