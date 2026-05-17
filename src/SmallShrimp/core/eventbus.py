from __future__ import annotations
"""事件总线 - 发布/订阅模式的事件分发中心。"""
import asyncio
import logging
from collections import defaultdict
from typing import Awaitable, Callable, TypeVar

from .events import Event
from ..server.worker import Worker

logger = logging.getLogger(__name__)

E = TypeVar("E", bound=Event)
Handler = Callable[[Event], Awaitable[None]]


class EventBus(Worker):
    """事件总线，支持订阅和异步分发。"""

    def __init__(self, context=None) -> None:
        super().__init__(context)
        self.context = context
        self._subscribers: dict[type[Event], list[Handler]] = defaultdict(list)
        self._queue: asyncio.Queue[Event] = asyncio.Queue()

    def subscribe(self, event_class: type[E], handler: Callable[[E], Awaitable[None]]) -> None:
        """订阅事件类型，注册处理器。"""
        self._subscribers[event_class].append(handler)
        logger.debug(f"已订阅 {event_class.__name__} 事件处理器")

    def unsubscribe(self, handler: Handler) -> None:
        """取消订阅，移除所有该处理器。"""
        for event_class in self._subscribers:
            if handler in self._subscribers[event_class]:
                self._subscribers[event_class].remove(handler)
                logger.debug(f"已取消订阅 {event_class.__name__} 事件处理器")

    async def publish(self, event: Event) -> None:
        """发布事件到内部队列（非阻塞）。"""
        await self._queue.put(event)
        logger.debug(f"已入队 {event.__class__.__name__} 事件")

    async def run(self) -> None:
        """从队列中处理事件。"""
        logger.info("EventBus 已启动")

        try:
            while True:
                event = await self._queue.get()
                try:
                    await self._dispatch(event)
                except Exception as e:
                    logger.error(f"分发事件时出错: {e}")
                finally:
                    self._queue.task_done()
        except asyncio.CancelledError:
            logger.info("EventBus 正在停止...")
            raise

    async def _dispatch(self, event: Event) -> None:
        """分发事件给订阅者。"""
        await self._notify_subscribers(event)
        logger.debug(f"已分发 {event.__class__.__name__} 事件")

    async def _notify_subscribers(self, event: Event) -> None:
        """通知所有订阅者（等待所有处理器完成）。"""
        handlers = self._subscribers.get(type(event), [])
        if not handlers:
            return

        tasks = [handler(event) for handler in handlers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"事件处理器出错: {result}")