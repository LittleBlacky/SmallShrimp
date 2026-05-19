
from __future__ import annotations

"""Context guard for proactive context window management."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Sequence
import re

from litellm import token_counter

if TYPE_CHECKING:
    from .session_state import SessionState
    from .memory import MemoryManager

from .message import Message, ToolMessage

MAX_TOOL_RESULT_CHARS = 10000

MEMORY_LINE_RE = re.compile(r"^[ \t]*MEMORY:\s*(.+?)(?:\s*\[tags:\s*([^\]]+)\])?\s*$", re.MULTILINE | re.IGNORECASE)

COMPACT_PROMPT = """Your task is two things:

1. SUMMARIZE the conversation concisely, capturing:
   - Primary Request and Intent
   - Key Facts and User Preferences
   - Current Work and Pending Tasks

2. EXTRACT important memories to save, format each as:
   MEMORY: <content> [tags: preference|fact|progress|context]

Here is the conversation:

{conversation}

Provide your summary and memories:"""


class ContextGuard:

    def __init__(self, token_threshold: int = 160000, memory_manager: "MemoryManager | None" = None):
        self.token_threshold = token_threshold  # 默认 80% of 200k context
        self.memory_manager = memory_manager

    def _get_memory_manager(self, state: "SessionState") -> "MemoryManager | None":
        """从 SessionState 获取 MemoryManager。"""
        if self.memory_manager:
            return self.memory_manager
        return None

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
        """压缩旧消息：用 LLM 总结历史，同时自动保存记忆。"""
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

        llm_output = summary_response.get("content", "")

        # 解析 MEMORY 行
        memory_mgr = self._get_memory_manager(state)
        if memory_mgr:
            for match in MEMORY_LINE_RE.finditer(llm_output):
                content = match.group(1).strip()
                tags_str = match.group(2) or ""
                tags = [t.strip() for t in tags_str.split(",")] if tags_str else []
                if content and "auto" not in tags:
                    tags.append("auto")
                if content:
                    try:
                        memory_mgr.remember(content, tags=tags if tags else ["auto"])
                    except Exception:
                        pass

        # 分离 summary 和其他内容（MEMORY 行不放入压缩消息）
        lines = llm_output.split("\n")
        summary_lines = [l for l in lines if not MEMORY_LINE_RE.match(l.strip())]
        summary = "\n".join(summary_lines).strip()

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
