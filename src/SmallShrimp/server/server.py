from __future__ import annotations
"""Server 协调器 - 管理所有 Workers。"""
import asyncio
import logging
from typing import TYPE_CHECKING

import uvicorn

from .worker import Worker
from .agent_worker import AgentWorker
from .delivery_worker import DeliveryWorker
from .channel_worker import ChannelWorker
from .websocket_worker import WebSocketWorker
from .cron_worker import CronWorker
from .app import create_app
from .context import Context

logger = logging.getLogger(__name__)


class Server:
    """协调所有 Workers 的服务器。"""

    def __init__(self, context: Context):
        self.context = context
        self.workers: list[Worker] = []
        self._api_task: asyncio.Task | None = None

    async def run(self) -> None:
        """启动所有 Workers 并监控崩溃。"""
        self._setup_workers()
        self._start_workers()

        try:
            await self._monitor_workers()
        except asyncio.CancelledError:
            logger.info("Server 正在关闭...")
            await self._stop_all()
            raise

    def _setup_workers(self) -> None:
        """创建所有 Workers。"""
        # 创建 WebSocketWorker 并附加到 context
        ws_worker = WebSocketWorker(self.context)
        self.context.websocket_worker = ws_worker

        self.workers = [
            self.context.eventbus,  # EventBus (主动 Worker)
            AgentWorker(self.context),  # SubscriberWorker
            DeliveryWorker(self.context),  # SubscriberWorker
            CronWorker(self.context),  # CronWorker (主动 Worker)
            ws_worker,  # WebSocketWorker (SubscriberWorker)
        ]

        # 如果有平台频道，也启动 ChannelWorker
        if hasattr(self.context, "channels") and self.context.channels:
            self.workers.append(ChannelWorker(self.context))
            logger.info(f"已启用 {len(self.context.channels)} 个平台频道")

        logger.info(f"Server 设置完成，共 {len(self.workers)} 个核心 Workers")

    def _start_workers(self) -> None:
        """启动所有 Workers。"""
        for worker in self.workers:
            worker.start()
            logger.info(f"已启动 {worker.__class__.__name__}")

    async def _monitor_workers(self) -> None:
        """监控 Workers，崩溃时重启。"""
        while True:
            for worker in self.workers:
                if worker.has_crashed():
                    exc = worker.get_exception()
                    if exc is None:
                        logger.warning(f"{worker.__class__.__name__} 意外退出")
                    else:
                        logger.error(f"{worker.__class__.__name__} 崩溃: {exc}")

                    worker.start()
                    logger.info(f"已重启 {worker.__class__.__name__}")

            await asyncio.sleep(5)

    async def _stop_all(self) -> None:
        """优雅停止所有 Workers。"""
        for worker in self.workers:
            await worker.stop()

    async def start_api(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        """启动 Web API 服务器。"""
        app = create_app(self.context)
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
        )
        server = uvicorn.Server(config)
        logger.info(f"WebSocket 服务器已启动: {host}:{port}")
        await server.serve()