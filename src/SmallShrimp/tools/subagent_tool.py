"""Subagent dispatch tool - 让 Agent 调度任务给其他 Agent。"""
from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

from ..core.events import AgentEventSource, DispatchEvent, DispatchResultEvent

if TYPE_CHECKING:
    from ..core.agent import AgentSession
    from ..server.context import Context
    from ..tools.base import Tool


def create_subagent_dispatch_tool(
    current_agent_id: str,
    context: "Context",
) -> "Tool | None":
    """创建 subagent_dispatch 工具，动态生成 schema 列出可用 Agent。"""

    available_agents = context.agent_loader.discover_agents()
    dispatchable = [a for a in available_agents if (a.id or a.name) != current_agent_id]

    if not dispatchable:
        return None

    # 构建描述
    agents_desc = "<available_agents>\n"
    for a in dispatchable:
        agents_desc += f'  <agent id="{a.id or a.name}">{a.description}</agent>\n'
    agents_desc += "</available_agents>"

    dispatchable_ids = [a.id or a.name for a in dispatchable]

    from ..tools.decorators import tool

    # 捕获外部 context，避免被工具参数 shadow
    _ctx = context

    @tool(
        name="subagent_dispatch",
        description=f"Dispatch a task to a specialized subagent.\n{agents_desc}",
    )
    async def subagent_dispatch(
        agent_id: str,
        task: str,
        session: "AgentSession",
        context: str = "",
    ) -> str:
        """调度任务给子 Agent，返回 JSON 结果。"""
        # 加载目标 Agent
        agent_def = _ctx.agent_loader.load(agent_id)
        from ..core.agent import Agent

        agent = Agent(
            agent_def,
            _ctx.config,
            _ctx.tool_registry,
            _ctx.history_manager,
            prompt_builder=_ctx.prompt_builder,
            memory_manager=_ctx.memory_manager,
        )
        agent_source = AgentEventSource(agent_id=current_agent_id)
        agent_session = agent.new_session(source=agent_source)
        session_id = agent_session.session_id

        user_message = f"{task}\n\nContext:\n{context}" if context else task

        loop = asyncio.get_running_loop()
        result_future: asyncio.Future[str] = loop.create_future()

        async def handle_result(event: DispatchResultEvent) -> None:
            if event.session_id == session_id:
                if not result_future.done():
                    if event.error:
                        result_future.set_exception(Exception(event.error))
                    else:
                        result_future.set_result(event.content)

        _ctx.eventbus.subscribe(DispatchResultEvent, handle_result)

        try:
            dispatch_event = DispatchEvent(
                session_id=session_id,
                source=agent_source,
                content=user_message,
                timestamp=time.time(),
                parent_session_id=session.session_id,
            )
            await _ctx.eventbus.publish(dispatch_event)

            response = await asyncio.wait_for(result_future, timeout=120.0)
        finally:
            _ctx.eventbus.unsubscribe(handle_result)

        return json.dumps({"result": response, "session_id": session_id}, ensure_ascii=False)

    return subagent_dispatch
