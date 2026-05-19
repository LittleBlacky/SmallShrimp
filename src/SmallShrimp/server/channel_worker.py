from __future__ import annotations
"""Channel Worker - 从平台接收消息，发布 InboundEvent。"""
import asyncio
import time
from typing import TYPE_CHECKING

from ..core.events import EventSource, InboundEvent
from .worker import Worker

if TYPE_CHECKING:
    from .context import Context


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

                session_id = self.context.routing_table.get_or_create_session_id(source)

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