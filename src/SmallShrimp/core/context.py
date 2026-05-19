"""Shared context - 所有组件的单一数据源。"""
from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING

from ..utils.config import Config
from .eventbus import EventBus
from .agent_loader import AgentLoader
from .skill_loader import SkillLoader
from .commands.registry import CommandRegistry
from .commands.handlers import CommandContext
from .prompt_builder import PromptBuilder

if TYPE_CHECKING:
    from .events import OutboundEvent, InboundEvent


class SharedContext:
    """全局共享状态 - 单例模式。

    统一管理所有核心组件，供 Worker、Agent、命令处理器等使用。
    """

    def __init__(self, config: Config, channels: list | None = None) -> None:
        self.config = config
        self.history_path = Path("workspace/sessions")
        self.channels = channels or []

        # 核心组件
        self.agent_loader = AgentLoader(Path("workspace/agents"))
        self.skill_loader = SkillLoader(Path("workspace/skills"))
        self.eventbus = EventBus(self)
        self.prompt_builder = PromptBuilder(self)

        # 命令注册表 - 自动注册内置命令
        self.command_registry = CommandRegistry.with_builtins()

    def subscribe(
        self,
        event_type: type,
        handler,
    ) -> None:
        """订阅事件。"""
        self.eventbus.subscribe(event_type, handler)

    async def publish(self, event) -> None:
        """发布事件。"""
        await self.eventbus.publish(event)

    def ack(self, event) -> None:
        """确认事件。"""
        self.eventbus.ack(event)


# 全局单例（CLI/Server 启动时初始化）
_context: SharedContext | None = None


def get_context() -> SharedContext:
    """获取全局上下文单例。"""
    if _context is None:
        raise RuntimeError("SharedContext not initialized. Call init_context() first.")
    return _context


def init_context(config: Config) -> SharedContext:
    """初始化全局上下文单例。"""
    global _context
    _context = SharedContext(config)
    return _context