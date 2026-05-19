
from __future__ import annotations

"""Context guard for proactive context window management."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from litellm import token_counter

if TYPE_CHECKING:
    from .session_state import SessionState

from .message import Message, ToolMessage

MAX_TOOL_RESULT_CHARS = 10000

COMPACT_PROMPT = """Your task is to create a detailed summary of the conversation so far, capturing the user's requests, your actions, and any important context needed to continue without losing information.

Your summary should include:
1. Primary Request and Intent
2. Key Facts and User Preferences
3. User Messages (ALL user messages)
4. Errors and Corrections
5. Current Work and Pending Tasks

Here is the conversation to summarize:

{conversation}

Please provide your summary following this structure."""


class ContextGuard:

    def __init__(self, token_threshold: int = 160000):
        self.token_threshold = token_threshold  # 默认 80% of 200k context

    def estimate_tokens(self, state: "SessionState") -> int:
        """估算当前消息列表的 token 数量"""
        messages = state.build_messages()
        try:
            model = state.agent.agent_def.llm.get("model", "gpt-4")
            return token_counter(model=model, messages=messages)
        except Exception:
            # 回退到简单估算
            return state._estimate_tokens(
                "".join(m.get("content", "") or "" for m in messages)
            )

    def _truncate_large_tool_results(self, messages: list["Message"]) -> list["Message"]:
        """截断过大的工具结果"""
        truncated = []
        for msg in messages:
            if isinstance(msg, ToolMessage) and len(msg.content) > MAX_TOOL_RESULT_CHARS:
                # 保留前 MAX_TOOL_RESULT_CHARS 字符，加上省略提示
                truncated_msg = ToolMessage(
                    content=msg.content[:MAX_TOOL_RESULT_CHARS] + "\n...[truncated]...",
                    tool_call_id=msg.tool_call_id,
                    name=msg.name,
                )
                truncated.append(truncated_msg)
            else:
                truncated.append(msg)
        return truncated

    async def _compact_messages(self, state: "SessionState") -> "SessionState":
        """压缩旧消息：用 LLM 总结历史。"""
        history_msgs = state.messages

        # 收集历史用于总结
        history_text = "\n".join([
            f"[{msg.__class__.__name__}]: {msg.content[:500]}"
            for msg in history_msgs
            if hasattr(msg, 'content') and msg.content
        ][:20])

        prompt = COMPACT_PROMPT.format(conversation=history_text)

        # 调用 LLM 生成总结
        summary_response = await state.agent.llm.chat([
            {"role": "user", "content": prompt}
        ])

        summary = summary_response.get("content", "")

        # 构建压缩后的消息：系统消息 + 总结消息 + 最近消息
        from .message import SystemMessage, AssistantMessage, HumanMessage

        # 提取系统消息
        system_msg = None
        for msg in state.messages:
            if isinstance(msg, SystemMessage):
                system_msg = msg
                break

        compact_messages: list[Message] = []
        if system_msg:
            compact_messages.append(system_msg)

        compact_messages.append(AssistantMessage(
            content=f"[Context Compacted] Previous conversation summary:\n\n{summary}"
        ))

        # 保留最后几条消息（避免丢失最近的上下文）
        recent_count = 4
        recent_msgs = state.messages[-recent_count:]
        for msg in recent_msgs:
            if not isinstance(msg, (SystemMessage, AssistantMessage)) or "Context Compacted" not in str(msg.content):
                compact_messages.append(msg)

        state.messages = compact_messages
        return state

    async def check_and_compact(self, state: "SessionState") -> "SessionState":
        """检查并压缩上下文"""
        # 1. 估算当前 token
        token_count = self.estimate_tokens(state)

        # 2. 没超限？直接返回
        if token_count < self.token_threshold:
            return state

        # 3. 超限了，先截断大工具结果
        state.messages = self._truncate_large_tool_results(state.messages)

        # 4. 截断后再检查
        if self.estimate_tokens(state) < self.token_threshold:
            return state

        # 5. 还是超限？调用 LLM 总结
        return await self._compact_messages(state)
