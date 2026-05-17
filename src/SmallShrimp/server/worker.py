from __future__ import annotations
"""Worker 生命周期管理基类。"""
import asyncio
import logging
from abc import ABC, abstractmethod


class Worker(ABC):
    """所有 Worker 的基类，包含生命周期管理。"""

    def __init__(self, context=None):
        self.context = context
        self.logger = logging.getLogger(f"SmallShrimp.{self.__class__.__name__}")
        self._task: asyncio.Task | None = None

    @abstractmethod
    async def run(self) -> None:
        """主 Worker 循环，持续运行直到被取消。"""
        pass

    def start(self) -> asyncio.Task:
        """启动 Worker 为 asyncio Task。"""
        self._task = asyncio.create_task(self.run())
        return self._task

    def is_running(self) -> bool:
        """检查 Worker 是否正在运行。"""
        return self._task is not None and not self._task.done()

    def has_crashed(self) -> bool:
        """检查 Worker 是否崩溃（已结束但未被取消）。"""
        return self._task is not None and self._task.done() and not self._task.cancelled()

    def get_exception(self) -> BaseException | None:
        """获取 Worker 崩溃时的异常，否则返回 None。"""
        if self.has_crashed() and self._task is not None:
            return self._task.exception()
        return None

    async def stop(self) -> None:
        """优雅地停止 Worker。"""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


class SubscriberWorker(Worker):
    """只订阅事件、无主动循环的 Worker。"""

    async def run(self) -> None:
        """等待取消信号 - 实际工作在事件处理器中进行。"""
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            pass