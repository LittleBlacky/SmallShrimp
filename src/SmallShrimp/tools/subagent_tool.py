"""Subagent dispatch tool — direct-call via run_once()."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

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

    # 捕获外部 context
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
        agent_type: str = "general",
    ) -> str:
        """调度任务给子 Agent，返回 JSON 结果。

        agent_type: explore (read-only), plan (read-only+planning), general (all tools)
        """
        if agent_id not in dispatchable_ids:
            return json.dumps(
                {"error": f"Unknown agent_id: {agent_id}. Available: {dispatchable_ids}"},
                ensure_ascii=False,
            )

        # 加载目标 Agent
        agent_def = _ctx.agent_loader.load(agent_id)
        from ..core.agent import Agent

        sub_agent = Agent(
            agent_def,
            _ctx.config,
            _ctx.tool_registry,
            _ctx.history_manager,
            prompt_builder=_ctx.prompt_builder,
            memory_manager=_ctx.memory_manager,
        )
        sub_session = sub_agent.new_session()

        user_message = f"{task}\n\nContext:\n{context}" if context else task

        # Validate agent_type
        valid_types = ("explore", "plan", "general")
        if agent_type not in valid_types:
            agent_type = "general"

        result = await sub_session.run_once(
            user_message,
            agent_type=agent_type,
        )

        # Aggregate tokens into parent session's usage
        if hasattr(session, '_subagent_tokens'):
            session._subagent_tokens += result.input_tokens + result.output_tokens
        else:
            session._subagent_tokens = result.input_tokens + result.output_tokens

        return json.dumps({
            "result": result.text,
            "session_id": result.session_id,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        }, ensure_ascii=False)

    return subagent_dispatch
