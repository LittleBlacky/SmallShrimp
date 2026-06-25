"""Post message tool - 让 Agent 主动向用户推送消息。

支持两种模式：
  1. 默认（无 platform 参数）→ 回复来源平台（旧行为）
  2. 指定 platform → 跨平台投递到指定目标
"""
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

    # 可用平台列表（供工具描述生成）
    available_platforms = []
    for c in channels:
        try:
            pn = c.platform_name
            if isinstance(pn, str):
                available_platforms.append(pn)
        except Exception:
            pass
    platforms_hint = ", ".join(available_platforms) if available_platforms else "default"

    from ..tools.decorators import tool

    @tool(
        name="post_message",
        description=(
            f"Send a message to the user via a messaging platform. "
            f"Available platforms: {platforms_hint}. "
            f"Use 'platform' to specify a target platform (e.g. 'telegram', 'discord'). "
            f"If omitted, replies to the user's original platform by default. "
            f"Use platform='all' to broadcast to every available platform."
        ),
    )
    async def post_message(
        content: str,
        session: "AgentSession",
        platform: str = "",
    ) -> str:
        """向用户主动推送消息。

        Args:
            content: 消息内容
            session: 当前会话（自动注入）
            platform: 目标平台，空=回复来源平台，"all"=广播到所有平台

        Returns:
            发送结果描述
        """
        from ..channels.target import DeliveryTarget

        delivery_target = None

        # 未指定 platform → 自动从 session 来源推断或 delivery_target 兜底
        if not platform or platform == "":
            # 优先用 session 的 delivery_target（cron 等无来源场景）
            if session.state.delivery_target:
                delivery_target = DeliveryTarget(
                    platform=session.state.delivery_target,
                    target_type="user",
                )
            else:
                # 从来源平台推断
                session_source = getattr(session.state, "source", None)
                if session_source and hasattr(session_source, "platform_name"):
                    pn = session_source.platform_name
                    if pn:
                        delivery_target = DeliveryTarget(platform=pn, target_type="user")

        elif platform == "all":
            # 广播：每个平台发一条
            sent = []
            for ch in channels:
                dt = DeliveryTarget(platform=ch.platform_name, target_type="user")
                event = OutboundEvent(
                    session_id=session.session_id,
                    source=AgentEventSource(agent_id=session.agent.agent_def.id),
                    content=content,
                    timestamp=time.time(),
                    delivery_target=dt,
                )
                await context.eventbus.publish(event)
                sent.append(ch.platform_name)
            return f"消息已广播到: {', '.join(sent)}"

        else:
            delivery_target = DeliveryTarget(platform=platform, target_type="user")

        # delivery_target 仍为 None → 无任何渠道可发
        if delivery_target is None:
            return "错误: 无法确定投递目标，请指定 platform 参数"

        event = OutboundEvent(
            session_id=session.session_id,
            source=AgentEventSource(agent_id=session.agent.agent_def.id),
            content=content,
            timestamp=time.time(),
            delivery_target=delivery_target,
        )
        await context.eventbus.publish(event)

        if delivery_target:
            return f"消息已发送到 {delivery_target.platform}"
        return "消息已发送"

    return post_message
