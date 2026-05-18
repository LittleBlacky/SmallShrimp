from __future__ import annotations
"""Channel Worker - 从平台接收消息，发布 InboundEvent。"""
import asyncio
import time
from typing import TYPE_CHECKING

from ..core.events import EventSource, InboundEvent
from .worker import Worker

if TYPE_CHECKING:
    from ..server.context import Context


class ChannelWorker(Worker):
    """从多个平台接收消息，发布 InboundEvent 到事件总线。"""

    def __init__(self, context: "Context"):
        super().__init__(context)
        self.channels = getattr(context, "channels", [])
        self.channel_map = {channel.platform_name: channel for channel in self.channels}

    async def run(self) -> None:
        """启动所有频道并处理传入消息。"""
        self.logger.info(f"ChannelWorker 已启动，管理 {len(self.channels)} 个频道")

        channel_tasks = [
            channel.run(self._create_callback(channel.platform_name))
            for channel in self.channels
        ]

        try:
            await asyncio.gather(*channel_tasks)
        except asyncio.CancelledError:
            await asyncio.gather(*[channel.stop() for channel in self.channels])
            raise

    def _create_callback(self, platform: str):
        """为指定平台创建回调函数。"""

        async def callback(message: str, source: EventSource) -> None:
            try:
                channel = self.channel_map[platform]

                if not channel.is_allowed(source):
                    self.logger.debug(f"忽略非白名单消息来自 {platform}")
                    return

                session_id = self._get_or_create_session_id(source)

                # 发布 InboundEvent
                event = InboundEvent(
                    session_id=session_id,
                    source=source,
                    content=message,
                    timestamp=time.time(),
                )
                await self.context.eventbus.publish(event)
                self.logger.debug(f"已发布来自 {source} 的 INBOUND 事件")

            except Exception as e:
                self.logger.error(f"处理来自 {platform} 的消息时出错: {e}")

        return callback

    def _get_or_create_session_id(self, source: EventSource) -> str:
        """获取或创建指定来源的会话 ID。"""
        source_str = str(source)

        # 从配置缓存中查找
        if hasattr(self.context, "config") and hasattr(self.context.config, "sources"):
            source_session = self.context.config.sources.get(source_str)
            if source_session:
                return source_session.session_id

        # 首次创建会话（需要 AgentLoader）
        if hasattr(self.context, "agent_loader"):
            default_agent = "pickle"
            if hasattr(self.context, "config") and hasattr(self.context.config, "default_agent"):
                default_agent = self.context.config.default_agent

            try:
                agent_def = self.context.agent_loader.load(default_agent)
                from ..core.agent import Agent

                agent = Agent(
                    agent_def,
                    self.context.config,
                    getattr(self.context, "tool_registry", None),
                    getattr(self.context, "history_manager", None),
                )
                session = agent.new_session(source)

                # 缓存会话 ID 到配置
                if hasattr(self.context, "config") and hasattr(self.context.config, "set_runtime"):
                    from ..utils.config import SourceSessionConfig
                    self.context.config.set_runtime(
                        f"sources.{source_str}",
                        SourceSessionConfig(session_id=session.session_id),
                    )

                return session.session_id
            except Exception as e:
                self.logger.warning(f"创建会话失败: {e}")

        # 回退：生成临时会话 ID
        import uuid
        return str(uuid.uuid4())[:8]