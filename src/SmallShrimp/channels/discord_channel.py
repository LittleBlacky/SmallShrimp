from __future__ import annotations
"""Discord 频道实现。"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Awaitable

from ..core.events import EventSource
from ..utils.config import DiscordConfig
from .base import Channel

logger = logging.getLogger(__name__)


@dataclass
class DiscordEventSource(EventSource):
    """Discord 来源的事件。"""
    _namespace = "platform-discord"
    user_id: str
    channel_id: str

    def __str__(self) -> str:
        return f"platform-discord:{self.user_id}:{self.channel_id}"

    @classmethod
    def from_string(cls, s: str) -> "DiscordEventSource":
        _, user_id, channel_id = s.split(":")
        return cls(user_id=user_id, channel_id=channel_id)

    @property
    def platform_name(self) -> str:
        return "discord"


class DiscordChannel(Channel[DiscordEventSource]):
    """Discord 平台实现。"""

    platform_name = "discord"

    def __init__(self, config: DiscordConfig):
        self.config = config
        self._client = None
        self._stop_event: asyncio.Event | None = None
        self._on_message: Callable | None = None

    def is_allowed(self, source: DiscordEventSource) -> bool:
        """检查发送者是否在白名单中。"""
        if not self.config.allowed_user_ids:
            return True
        return source.user_id in self.config.allowed_user_ids

    async def run(self, on_message: Callable[[str, DiscordEventSource], Awaitable[None]]) -> None:
        """启动 Discord 频道。"""
        self._on_message = on_message
        self._stop_event = asyncio.Event()

        try:
            import discord
        except ImportError:
            raise ImportError("discord.py 未安装，请运行: pip install discord.py")

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_message(msg: discord.Message):
            if msg.author == self._client.user:
                return

            user_id = str(msg.author.id)
            channel_id = str(msg.channel.id)

            source = DiscordEventSource(user_id=user_id, channel_id=channel_id)

            try:
                if self._on_message:
                    await self._on_message(msg.content, source)
            except Exception as e:
                logger.error(f"消息回调出错: {e}")

        @self._client.event
        async def on_ready():
            logger.info(f"Discord 已登录为 {self._client.user}")

        self._client.run(self.config.bot_token, loop=asyncio.get_event_loop())

    async def reply(self, content: str, source: DiscordEventSource) -> None:
        """回复消息。"""
        if not self._client:
            raise RuntimeError("DiscordChannel 未启动")

        try:
            import discord
            channel = self._client.get_channel(int(source.channel_id))
            if channel:
                await channel.send(content)
        except Exception as e:
            logger.error(f"Discord 回复失败: {e}")
            raise

    async def stop(self) -> None:
        """停止 Discord bot。"""
        if self._client:
            await self._client.close()
        if self._stop_event:
            self._stop_event.set()
        self._client = None
