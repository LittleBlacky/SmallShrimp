from __future__ import annotations
"""事件总线 - 发布/订阅模式的事件分发中心。"""
import asyncio
import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, TypeVar

from .events import Event, OutboundEvent, deserialize_event
from ..server.worker import Worker

if TYPE_CHECKING:
    from ..server.context import Context

logger = logging.getLogger(__name__)

E = TypeVar("E", bound=Event)
Handler = Callable[[Event], Awaitable[None]]


class EventBus(Worker):
    """事件总线，支持订阅和异步分发。"""

    def __init__(self, context: "Context | None" = None) -> None:
        super().__init__(context)
        self.context = context
        self._subscribers: dict[type[Event], list[Handler]] = defaultdict(list)
        self._queue: asyncio.Queue[Event] = asyncio.Queue()

        # 待投递事件目录（用于持久化和故障恢复）
        self.pending_dir: Path | None = None
        if context and hasattr(context, "config") and context.config:
            self.pending_dir = context.config.workspace / "events" / "pending"
            self.pending_dir.mkdir(parents=True, exist_ok=True)

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

        # 启动时恢复待投递事件
        if self.pending_dir:
            await self._recover()

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
        await self._persist_outbound(event)
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

    async def _persist_outbound(self, event: Event) -> None:
        """持久化 OutboundEvent 到磁盘。"""
        if not isinstance(event, OutboundEvent) or not self.pending_dir:
            return

        filename = f"{event.timestamp}_{event.session_id}.json"
        final_path = self.pending_dir / filename
        tmp_path = self.pending_dir / f".tmp.{os.getpid()}.{filename}"

        data = json.dumps(event.to_dict(), ensure_ascii=False)

        # 原子写入：tmp 文件 + fsync + rename
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        os.replace(str(tmp_path), str(final_path))
        logger.debug(f"持久化事件到 {final_path}")

    async def _recover(self) -> int:
        """从磁盘恢复上次崩溃前的待投递事件。返回恢复数量。"""
        if not self.pending_dir:
            return 0

        pending_files = list(self.pending_dir.glob("*.json"))
        if not pending_files:
            return 0

        logger.info(f"恢复 {len(pending_files)} 个待投递事件")
        count = 0

        for file_path in pending_files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                event = deserialize_event(data)
                await self._notify_subscribers(event)
                count += 1
                logger.debug(f"已恢复事件: {file_path.name}")
            except Exception as e:
                logger.error(f"恢复事件失败 {file_path}: {e}")

        logger.info(f"已恢复 {count} 个事件")
        return count

    def ack(self, event: Event) -> None:
        """确认投递成功，删除持久化的事件文件。"""
        if not self.pending_dir:
            return

        filename = f"{event.timestamp}_{event.session_id}.json"
        final_path = self.pending_dir / filename
        if final_path.exists():
            final_path.unlink()
            logger.debug(f"已确认并删除 {filename}")