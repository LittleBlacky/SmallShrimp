from __future__ import annotations
"""Agent Worker - 执行 Agent 任务的 Worker。"""
import asyncio
import logging
from dataclasses import replace

from .worker import SubscriberWorker
from ..core.agent import Agent
from ..core.events import InboundEvent, OutboundEvent

logger = logging.getLogger(__name__)

# 会话失败时的最大重试次数
MAX_RETRIES = 3


class AgentWorker(SubscriberWorker):
    """将事件分发给会话执行器的 Worker。"""

    def __init__(self, context: "Context") -> None:
        super().__init__(context)
        # 自动订阅事件
        self.context.eventbus.subscribe(InboundEvent, self.dispatch_event)
        self.logger.info("AgentWorker 已订阅 InboundEvent 事件")

    async def dispatch_event(self, event: InboundEvent) -> None:
        """为类型事件创建执行器任务。"""
        session_id = event.session_id

        # 从会话信息获取 agent_id（单一数据源）
        session_info = self.context.history_manager.get_session_info(session_id)
        if not session_info:
            logger.error(f"会话不存在: {session_id}")
            return

        agent_id = session_info.get("agent_id", "pickle")  # 默认为 pickle

        try:
            agent_def = self.context.agent_loader.load(agent_id)
        except Exception as e:
            logger.error(f"Agent 不存在: {agent_id}: {e}")
            await self._emit_response(event, "", str(e))
            return

        # 创建任务执行会话
        asyncio.create_task(self.exec_session(event, agent_def))

    async def exec_session(self, event: InboundEvent, agent_def) -> None:
        """使用给定 Agent 执行会话。"""
        session_id = event.session_id

        try:
            # 使用依赖创建 Agent
            agent = Agent(
                agent_def,
                self.context.config,
                self.context.tool_registry,
                self.context.history_manager,
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
                cmd_context = CommandContext(session)
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

            await self.context.eventbus.publish(
                OutboundEvent(session_id=session_id, content=response)
            )

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

    async def _emit_response(
        self, event: InboundEvent, content: str, error: str | None = None
    ) -> None:
        """发送带内容的响应事件。"""
        await self.context.eventbus.publish(
            OutboundEvent(
                session_id=event.session_id,
                content=content,
                error=str(error) if error else None,
            )
        )