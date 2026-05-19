from __future__ import annotations
"""Channel 抽象基类 - 消息平台的统一接口。"""
from abc import ABC, abstractmethod
from typing import Callable, Awaitable, Generic, TypeVar, Any

from ..core.events import EventSource

T = TypeVar("T", bound=EventSource)


class Channel(ABC, Generic[T]):
    """消息平台抽象基类。

    子类必须实现：platform_name, reply, is_allowed
    子类可选实现：run, stop（默认 no-op，纯输出 Channel 不需要）
    """

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """平台标识符。"""
        ...

    async def run(self, on_message: Callable[[str, T], Awaitable[None]]) -> None:
        """启动频道（默认 no-op，纯输出 Channel 不 override）。"""
        pass

    @abstractmethod
    def is_allowed(self, source: T) -> bool:
        """检查发送者是否在白名单中。"""
        ...

    @abstractmethod
    async def reply(self, content: str, source: T) -> None:
        """回复消息。"""
        ...

    async def stop(self) -> None:
        """停止监听（默认 no-op）。"""
        pass

    @property
    def max_message_length(self) -> int:
        """单条消息最大长度，默认无限制。"""
        return 2**31  # 近似无限