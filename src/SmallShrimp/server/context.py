from __future__ import annotations
"""应用上下文 - 依赖注入容器。"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.agent_loader import AgentLoader
    from ..core.history import HistoryManager
    from ..core.eventbus import EventBus
    from ..core.commands.registry import CommandRegistry
    from ..tools.registry import ToolRegistry
    from ..utils.config import Config
    from ..channels.base import Channel


@dataclass
class Context:
    """应用上下文，用于依赖注入。"""
    config: "Config"
    agent_loader: "AgentLoader"
    history_manager: "HistoryManager"
    tool_registry: "ToolRegistry"
    eventbus: "EventBus"
    command_registry: "CommandRegistry"
    workspace: Path = field(default_factory=lambda: Path("workspace"))
    channels: list["Channel"] = field(default_factory=list)

    @classmethod
    def from_workspace(cls, workspace: Path) -> "Context":
        """从工作区路径创建 Context。"""
        from ..utils.config import Config
        from ..core.agent_loader import AgentLoader
        from ..core.history import HistoryManager
        from ..core.eventbus import EventBus
        from ..core.commands.registry import CommandRegistry
        from ..tools import create_tool_registry
        from ..channels import create_channels_from_config

        config = Config.from_yaml(workspace / "config.user.yaml")
        config.workspace = workspace

        agent_loader = AgentLoader(workspace / "agents")
        history_manager = HistoryManager(workspace / "sessions")
        eventbus = EventBus()
        command_registry = CommandRegistry()

        # 创建工具注册表
        config_dict = config.data.copy()
        config_dict["skills_dir"] = str(workspace / "skills")
        tool_registry = create_tool_registry(config_dict)

        # 从配置创建 Channel
        channels = create_channels_from_config(config)

        return cls(
            config=config,
            agent_loader=agent_loader,
            history_manager=history_manager,
            tool_registry=tool_registry,
            eventbus=eventbus,
            command_registry=command_registry,
            workspace=workspace,
            channels=channels,
        )