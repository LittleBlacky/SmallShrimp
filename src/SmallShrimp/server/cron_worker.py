"""Cron worker for scheduled job dispatch."""
from __future__ import annotations

import asyncio
import logging
import shutil
from typing import TYPE_CHECKING

from .worker import Worker
from ..core.events import CronEventSource, DispatchEvent
from ..core.cron_loader import find_due_jobs

if TYPE_CHECKING:
    from .context import Context

logger = logging.getLogger(__name__)


class CronWorker(Worker):
    """每分钟检查到期任务，发布 DispatchEvent。"""

    def __init__(self, context: "Context"):
        super().__init__(context)

    async def run(self) -> None:
        """每分钟 tick 一次。"""
        self.logger.info("CronWorker 已启动")

        while True:
            try:
                await self._tick()
            except Exception as e:
                self.logger.error(f"CronWorker tick 错误: {e}")

            await asyncio.sleep(60)

    async def _tick(self) -> None:
        """查找并调度到期任务。"""
        jobs = self.context.cron_loader.discover_crons()
        due_jobs = find_due_jobs(jobs)

        for cron_def in due_jobs:
            agent_def = self.context.agent_loader.load(cron_def.agent)
            from ..core.agent import Agent

            agent = Agent(
                agent_def,
                self.context.config,
                self.context.tool_registry,
                self.context.history_manager,
                prompt_builder=self.context.prompt_builder,
            )
            cron_source = CronEventSource(cron_id=cron_def.id)
            session = agent.new_session(source=cron_source)

            event = DispatchEvent(
                session_id=session.session_id,
                source=cron_source,
                content=cron_def.prompt,
            )
            await self.context.eventbus.publish(event)
            self.logger.info(f"已调度定时任务: {cron_def.id}")

            # 一次性任务执行后删除
            if cron_def.one_off:
                cron_path = self.context.cron_loader.crons_dir / cron_def.id
                if cron_path.exists():
                    shutil.rmtree(cron_path)
                    self.logger.info(f"已删除一次性定时任务: {cron_def.id}")
