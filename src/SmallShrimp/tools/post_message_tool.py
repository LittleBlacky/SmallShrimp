"""Post message tool - 让 Agent 主动向用户推送消息。"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from ..core.events import AgentEventSource, OutboundEvent

if TYPE_CHECKING:
    from ..core.agent import AgentSession
    from ..server.context import Context
    from ..tools.base import Tool


def create_post_message_tool(context: "Context") -> "Tool | None":
    """创建 post_message 工具。无渠道时返回 None。"""
    channels = getattr(context, "channels", [])
    if not channels:
        return None

    from ..tools.decorators import tool

    @tool(
        name="post_message",
        description="Send a message to the user via the default messaging platform. Use this to proactively notify the user about completed tasks, cron results, or important updates.",
    )
    async def post_message(content: str, session: "AgentSession") -> str:
        """向用户主动推送消息。"""
        event = OutboundEvent(
            session_id=session.session_id,
            source=AgentEventSource(agent_id=session.agent.agent_def.id),
            content=content,
            timestamp=time.time(),
        )
        await context.eventbus.publish(event)
        return "消息已发送"

    return post_message
