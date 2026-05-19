"""企业微信群机器人 Channel。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Awaitable

import aiohttp

from ..core.events import EventSource
from .base import Channel

logger = logging.getLogger(__name__)


@dataclass
class WeComEventSource(EventSource):
    """企业微信来源的事件。"""

    _namespace = "platform-wecom"
    webhook_key: str = ""

    def __str__(self) -> str:
        return f"platform-wecom:{self.webhook_key}"

    @classmethod
    def from_string(cls, s: str) -> "WeComEventSource":
        _, key = s.split(":", 1)
        return cls(webhook_key=key)

    @property
    def platform_name(self) -> str:
        return "wecom"


class WeComChannel(Channel[WeComEventSource]):
    """企业微信群机器人 Channel。

    仅支持出方向（Agent → 群聊），入方向需企业微信应用 + 回调服务器。
    """

    platform_name = "wecom"

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self._session: aiohttp.ClientSession | None = None

    def is_allowed(self, source: WeComEventSource) -> bool:
        return True  # 出方向 Channel，不校验来源

    async def run(self, on_message: Callable[[str, WeComEventSource], Awaitable[None]]) -> None:
        """企业微信群机器人不支持收消息，run 为空操作。"""
        pass

    async def reply(self, content: str, source: WeComEventSource) -> None:
        """发送消息到群聊。"""
        if not self._session:
            self._session = aiohttp.ClientSession()

        payload = {
            "msgtype": "text",
            "text": {"content": content},
        }

        try:
            async with self._session.post(self.webhook_url, json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(f"企业微信发送失败: {resp.status} {body}")
        except Exception as e:
            logger.error(f"企业微信发送异常: {e}")

    async def stop(self) -> None:
        """清理资源。"""
        if self._session:
            await self._session.close()
            self._session = None
