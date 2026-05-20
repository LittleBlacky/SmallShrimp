
from __future__ import annotations

"""Context guard for proactive context window management.

4-tier compaction (aligned with claude-code-from-scratch, zero-cost first):
  Tier 1 (Budget):     Head+tail truncation of large tool results
  Tier 2 (Snip):       Replace stale/duplicate reads with placeholders
  Tier 3 (Microcompact): Drop old tool results after inactivity
  Tier 4 (Autocompact): LLM summary (API call)
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
import time

from litellm import token_counter

if TYPE_CHECKING:
    from .session_state import SessionState

from .message import Message, ToolMessage, HumanMessage

BUDGET_TIER1_CHARS = 30000  # 50-70% context full → 30KB per result
BUDGET_TIER2_CHARS = 15000  # >70% full → 15KB per result
MICROCOMPACT_IDLE_SECONDS = 60

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

    def __init__(
        self,
        token_threshold: int = 160000,
        context_window: int = 200000,
    ):
        self.token_threshold = token_threshold
        self.context_window = context_window
        self._last_activity: float = time.time()
        self._seen_files: dict[str, int] = {}  # file → last_seen_msg_index

    def _fill_ratio(self, tokens: int) -> float:
        return tokens / self.context_window

    def estimate_tokens(self, state: "SessionState") -> int:
        """估算当前消息列表的 token 数量"""
        messages = state.build_messages()
        try:
            model = state.agent.agent_def.llm.get("model", "gpt-4")
            return token_counter(model=model, messages=messages)
        except Exception:
            return state._estimate_tokens(
                "".join(m.get("content", "") or "" for m in messages)
            )

    # ── Budget ──────────────────────────────────────────────
    def _budget_truncate(self, messages: list["Message"]) -> list["Message"]:
        """头尾截断大工具结果。LLM 可重跑工具获取完整结果，非信息丢失。"""
        tokens = self.estimate_tokens_raw(messages)
        ratio = tokens / max(self.context_window, 1)
        if ratio < 0.5:
            return messages
        budget = BUDGET_TIER2_CHARS if ratio > 0.7 else BUDGET_TIER1_CHARS

        result: list[Message] = []
        for msg in messages:
            if isinstance(msg, ToolMessage) and msg.content and len(msg.content) > budget:
                keep_each = (budget - 80) // 2
                if keep_each <= 0:
                    keep_each = budget // 2
                truncated = (
                    msg.content[:keep_each]
                    + f"\n\n[...budgeted: {len(msg.content) - keep_each * 2} chars truncated, re-run tool for full result...]\n\n"
                    + msg.content[-keep_each:]
                )
                result.append(ToolMessage(
                    content=truncated,
                    tool_call_id=msg.tool_call_id,
                    name=msg.name,
                ))
            else:
                result.append(msg)
        return result

    def estimate_tokens_raw(self, messages: list["Message"]) -> int:
        """估算原始消息列表的 token（不通过 state）。"""
        model = "gpt-4"
        try:
            dict_msgs = [msg.to_dict() if hasattr(msg, 'to_dict') else msg for msg in messages]
            return token_counter(model=model, messages=dict_msgs)
        except Exception:
            return sum(len(getattr(m, 'content', '') or '') // 4 for m in messages)

    # ── Snip ────────────────────────────────────────────────
    def _snip_duplicates(self, messages: list["Message"]) -> list["Message"]:
        """替换重复读取为占位符，保留最近一次。"""
        # 追踪文件读取
        file_reads: dict[str, int] = {}  # file → last_index
        for i, msg in enumerate(messages):
            if isinstance(msg, ToolMessage) and msg.name == "read":
                content = msg.content or ""
                # 提取文件名：content 以文件内容开头
                file_reads[content[:80]] = i

        # 标记旧的重复读取
        result: list[Message] = []
        for i, msg in enumerate(messages):
            if isinstance(msg, ToolMessage) and msg.name == "read":
                content = msg.content or ""
                key = content[:80]
                last_idx = file_reads.get(key, i)
                if i < last_idx:
                    # 旧的读取，替换为占位符
                    result.append(ToolMessage(
                        content=f"[Content snipped: previously read, see result at index {last_idx}]",
                        tool_call_id=msg.tool_call_id,
                        name=msg.name,
                    ))
                    continue
            result.append(msg)
        return result

    # ── Microcompact ────────────────────────────────────────
    def _microcompact(self, messages: list["Message"]) -> list["Message"]:
        """删除旧工具结果，保留最后 N 个用户消息相关的内容。"""
        # 找到最后几个用户消息的索引
        user_indices = []
        for i, msg in enumerate(messages):
            if isinstance(msg, HumanMessage):
                user_indices.append(i)

        if len(user_indices) < 3:
            return messages  # 不够，不清理

        # 保留最后 4 个用户消息之后的所有消息
        cutoff = max(0, user_indices[-4] if len(user_indices) >= 4 else user_indices[0])

        # 移除 cutoff 之前的 ToolMessage
        result = []
        for i, msg in enumerate(messages):
            if i < cutoff and isinstance(msg, ToolMessage):
                continue
            result.append(msg)
        return result

    # ── Autocompact ─────────────────────────────────────────
    async def _autocompact(self, state: "SessionState") -> "SessionState":
        """LLM 总结历史（API 调用）。"""
        history_msgs = state.messages
        history_text = "\n".join([
            f"[{msg.__class__.__name__}]: {msg.content[:500]}"
            for msg in history_msgs
            if hasattr(msg, 'content') and msg.content
        ][:20])

        prompt = COMPACT_PROMPT.format(conversation=history_text)
        summary_response = await state.agent.llm.chat([
            {"role": "user", "content": prompt}
        ])
        summary = summary_response.get("content", "")

        from .message import SystemMessage, AssistantMessage

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

        recent_count = 4
        recent_msgs = state.messages[-recent_count:]
        for msg in recent_msgs:
            if not isinstance(msg, (SystemMessage, AssistantMessage)) or "Context Compacted" not in str(msg.content):
                compact_messages.append(msg)

        state.messages = compact_messages
        self._last_activity = time.time()
        return state

    # ── Main check ────────────────────────────────────────────
    async def check_and_compact(self, state: "SessionState") -> "SessionState":
        """4 阶段压缩：Budget → Snip → Microcompact → Autocompact。"""
        tokens = self.estimate_tokens(state)

        if tokens < self.token_threshold:
            return state

        # Budget — 头尾截断大工具结果
        state.messages = self._budget_truncate(state.messages)
        if self.estimate_tokens(state) < self.token_threshold:
            return state

        # Snip — 替换重复读取
        state.messages = self._snip_duplicates(state.messages)
        if self.estimate_tokens(state) < self.token_threshold:
            return state

        # Microcompact — 清理旧工具结果（无损：只删旧数据）
        now = time.time()
        if now - self._last_activity > MICROCOMPACT_IDLE_SECONDS:
            state.messages = self._microcompact(state.messages)
            self._last_activity = now
            if self.estimate_tokens(state) < self.token_threshold:
                return state

        # Autocompact — LLM 总结
        return await self._autocompact(state)
