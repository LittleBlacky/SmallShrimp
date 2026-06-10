from __future__ import annotations
"""应用上下文 - 依赖注入容器。"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..core.routing import RoutingTable

if TYPE_CHECKING:
    from ..core.agent_loader import AgentLoader
    from ..core.cron_loader import CronLoader
    from ..core.history import HistoryManager
    from ..core.eventbus import EventBus
    from ..core.commands.registry import CommandRegistry
    from ..core.prompt_builder import PromptBuilder
    from ..core.memory import MemoryManager
    from ..core.skill_loader import SkillLoader
    from ..tools.registry import ToolRegistry
    from ..utils.config import Config
    from ..channels.base import Channel


@dataclass
class Context:
    """应用上下文，用于依赖注入。"""

    config: "Config"
    agent_loader: "AgentLoader"
    skill_loader: "SkillLoader"
    history_manager: "HistoryManager"
    tool_registry: "ToolRegistry"
    eventbus: "EventBus"
    command_registry: "CommandRegistry"
    prompt_builder: "PromptBuilder"
    memory_manager: "MemoryManager"
    cron_loader: "CronLoader"
    workspace: Path = field(default_factory=lambda: Path("workspace"))
    channels: list["Channel"] = field(default_factory=list)
    routing_table: "RoutingTable | None" = field(default=None)
    websocket_worker: "WebSocketWorker | None" = field(default=None)

    @classmethod
    def from_workspace(cls, workspace: Path) -> "Context":
        """从工作区路径创建完整的 Context。"""
        from ..utils.config import Config
        from ..core.agent_loader import AgentLoader
        from ..core.skill_loader import SkillLoader
        from ..core.history import HistoryManager
        from ..core.eventbus import EventBus
        from ..core.commands.registry import CommandRegistry
        from ..core.prompt_builder import PromptBuilder
        from ..core.memory import MemoryManager
        from ..core.cron_loader import CronLoader
        from ..tools import create_tool_registry
        from ..channels import create_channels_from_config

        config = Config.from_yaml(workspace / "config.user.yaml")
        config.workspace = workspace

        agent_loader = AgentLoader(workspace / "agents")
        skill_loader = SkillLoader(workspace / "skills")
        history_manager = HistoryManager(workspace / "sessions")
        prompt_builder = PromptBuilder(workspace)
        memory_manager = MemoryManager(workspace / "memories")
        cron_loader = CronLoader(workspace / "crons")

        # 事件总线
        pending_dir = workspace / "events" / "pending"
        eventbus = EventBus(pending_dir)
        command_registry = CommandRegistry()

        # 创建工具注册表
        config_dict = config.data.copy()
        config_dict["skills_dir"] = str(workspace / "skills")
        tool_registry = create_tool_registry(config_dict)

        # 从配置创建 Channel
        channels = create_channels_from_config(config)

        # 先创建 Context 以支持 RoutingTable 的反向引用
        context = cls(
            config=config,
            agent_loader=agent_loader,
            skill_loader=skill_loader,
            history_manager=history_manager,
            tool_registry=tool_registry,
            eventbus=eventbus,
            command_registry=command_registry,
            prompt_builder=prompt_builder,
            memory_manager=memory_manager,
            cron_loader=cron_loader,
            workspace=workspace,
            channels=channels,
        )

        # RoutingTable 需要 Context 引用
        context.routing_table = RoutingTable(context)

        # 统一注册依赖 Context 的工具
        from ..tools import register_context_tools
        register_context_tools(context.tool_registry, context)

        return context

    def close(self) -> None:
        """释放资源（关闭内存管理器后端等）。"""
        if hasattr(self, "memory_manager") and self.memory_manager is not None:
            self.memory_manager.close()