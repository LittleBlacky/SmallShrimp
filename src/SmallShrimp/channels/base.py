from __future__ import annotations
"""Channel 抽象基类 - 消息平台的统一接口。"""
from abc import ABC, abstractmethod
from typing import Callable, Awaitable, Generic, TypeVar, Any

from ..core.events import EventSource

T = TypeVar("T", bound=EventSource)


class Channel(ABC, Generic[T]):
    """消息平台抽象基类。"""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """平台标识符。"""
        ...

    @abstractmethod
    async def run(self, on_message: Callable[[str, T], Awaitable[None]]) -> None:
        """启动频道，阻塞直到 stop() 被调用。"""
        ...

    @abstractmethod
    def is_allowed(self, source: T) -> bool:
        """检查发送者是否在白名单中。"""
        ...

    @abstractmethod
    async def reply(self, content: str, source: T) -> None:
        """回复消息。"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """停止监听并清理资源。"""
        ...