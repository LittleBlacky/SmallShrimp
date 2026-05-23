from __future__ import annotations
"""Agent Worker - 执行 Agent 任务的 Worker。"""
import asyncio
import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from .worker import SubscriberWorker
from ..core.agent import Agent
from ..core.events import (
    InboundEvent, OutboundEvent, CliEventSource,
    AgentEventSource, DispatchEvent, DispatchResultEvent,
)
from ..core.commands.registry import CommandRegistry
from typing import Union

if TYPE_CHECKING:
    from .context import Context

logger = logging.getLogger(__name__)

# 会话失败时的最大重试次数
MAX_RETRIES = 3


class AgentWorker(SubscriberWorker):
    """将事件分发给会话执行器的 Worker，按用户控制并发。

    同一用户最多 per_user_concurrency 个并发 turn。
    """

    CLEANUP_THRESHOLD = 5
    DEFAULT_PER_USER_CONCURRENCY = 3

    def __init__(self, context: "Context") -> None:
        super().__init__(context)
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._cleanup_counter = 0
        self.context.eventbus.subscribe(InboundEvent, self.dispatch_event)
        self.context.eventbus.subscribe(DispatchEvent, self.dispatch_event)
        self.logger.info("AgentWorker 已订阅 InboundEvent 和 DispatchEvent 事件")

    def _user_key(self, source) -> str:
        """从事件来源提取用户标识。"""
        return str(getattr(source, 'source', source))

    def _get_or_create_semaphore(self, key: str, limit: int) -> asyncio.Semaphore:
        """获取或创建指定用户的信号量。"""
        if key not in self._semaphores:
            self._semaphores[key] = asyncio.Semaphore(limit)
        return self._semaphores[key]

    def _maybe_cleanup_semaphores(self) -> None:
        """定期清理完全空闲的信号量。"""
        self._cleanup_counter += 1
        if self._cleanup_counter < self.CLEANUP_THRESHOLD:
            return
        self._cleanup_counter = 0
        stale = [
            key for key, sem in self._semaphores.items()
            if not sem._waiters and sem._value == self.DEFAULT_PER_USER_CONCURRENCY
        ]
        for key in stale:
            del self._semaphores[key]

    async def dispatch_event(self, event: ProcessableEvent) -> None:
        """为类型事件创建执行器任务。"""
        session_id = event.session_id

        # 从会话信息获取 agent_id（单一数据源）
        session_info = self.context.history_manager.get_session_info(session_id)
        if not session_info:
            logger.error(f"会话不存在: {session_id}")
            return

        agent_id = session_info.get("agent_id") or self.context.config.default_agent

        try:
            agent_def = self.context.agent_loader.load(agent_id)
        except Exception as e:
            logger.error(f"Agent 不存在: {agent_id}: {e}")
            await self._emit_response(event, "", str(e))
            return

        # 创建任务执行会话
        asyncio.create_task(self.exec_session(event, agent_def))

    async def exec_session(self, event: ProcessableEvent, agent_def: "AgentDef") -> None:
        """使用给定 Agent 执行会话（按用户控制并发）。"""
        user_key = self._user_key(event.source if hasattr(event, 'source') else event)
        limit = agent_def.max_concurrency if agent_def.max_concurrency > 0 else self.DEFAULT_PER_USER_CONCURRENCY
        sem = self._get_or_create_semaphore(user_key, limit)
        session_id = event.session_id

        async with sem:
            try:
                # 使用依赖创建 Agent
                agent = Agent(
                    agent_def,
                    self.context.config,
                    self.context.tool_registry,
                    self.context.history_manager,
                    prompt_builder=self.context.prompt_builder,
                    memory_manager=self.context.memory_manager,
                )

                # 恢复或创建会话
                if session_id:
                    try:
                        session = agent.resume_session(session_id)
                    except ValueError:
                        logger.warning(f"会话 {session_id} 不存在，创建新会话")
                        session = agent.new_session(session_id=session_id)
                else:
                    session = agent.new_session()
                    session_id = session.session_id

                # 优先检查斜杠命令
                if event.content.startswith("/"):
                    from ..core.commands.handlers import CommandContext
                    cmd_context = CommandContext(
                        session,
                        routing_table=self.context.routing_table,
                        memory_manager=self.context.memory_manager,
                    )
                    result = await self.context.command_registry.dispatch(
                        event.content, cmd_context
                    )
                    if result:
                        await self._emit_response(event, result)
                        logger.info(f"命令执行完成: {session_id}")
                        return

                # 普通聊天
                response = await session.chat(event.content)
                logger.info(f"会话执行完成: {session_id}")

                await self._emit_response(event, response)

            except Exception as e:
                logger.error(f"会话执行失败: {e}")

                if event.retry_count < MAX_RETRIES:
                    # 指数退避重试
                    retry_event = replace(
                        event,
                        retry_count=event.retry_count + 1,
                        content=".",  # 重试时发送最小消息
                    )
                    await asyncio.sleep(0.5 * (2 ** event.retry_count))  # 0.5s, 1s, 2s
                    await self.context.eventbus.publish(retry_event)
                else:
                    await self._emit_response(event, "", str(e))

        self._maybe_cleanup_semaphores()

    async def _emit_response(
        self, event: ProcessableEvent, content: str, error: str | None = None
    ) -> None:
        """发送响应。DispatchEvent → DispatchResultEvent，否则 → OutboundEvent。"""
        if isinstance(event, DispatchEvent):
            result_event = DispatchResultEvent(
                session_id=event.session_id,
                source=event.source,
                content=content,
                error=error,
            )
        else:
            source = event.source if hasattr(event, "source") and event.source else CliEventSource()
            result_event = OutboundEvent(
                session_id=event.session_id,
                source=source,
                content=content,
                error=error,
            )
        await self.context.eventbus.publish(result_event)
