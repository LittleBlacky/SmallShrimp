
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
import os
import time

from litellm import token_counter

if TYPE_CHECKING:
    from .session_state import SessionState

from .message import Message, ToolMessage, HumanMessage

BUDGET_TIER1_CHARS = 30000
BUDGET_TIER2_CHARS = 15000
PERSIST_THRESHOLD = 30 * 1024    # 30KB: larger results persisted to disk
PERSIST_PREVIEW_LINES = 200       # lines to show in preview
SNIP_THRESHOLD = 0.60             # snip when >60% context full
KEEP_RECENT_RESULTS = 3           # keep last N tool results
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
        offload_dir: str | None = None,
    ):
        self.token_threshold = token_threshold
        self.context_window = context_window
        self.offload_dir = offload_dir or os.path.join(os.getcwd(), "workspace", ".cache", "tool_results")
        self._last_activity: float = time.time()

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

    # ── Persist ─────────────────────────────────────────────
    def _persist_large_result(self, msg: ToolMessage) -> ToolMessage:
        """>30KB 结果落盘，消息中保留 200 行预览 + 文件路径。"""
        content = msg.content or ""
        if len(content.encode("utf-8")) <= PERSIST_THRESHOLD:
            return msg

        os.makedirs(self.offload_dir, exist_ok=True)
        filename = f"{msg.name or 'tool'}_{msg.tool_call_id or 'result'}.txt"
        filepath = os.path.join(self.offload_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        lines = content.split("\n")
        size_kb = len(content.encode("utf-8")) / 1024
        preview = "\n".join(lines[:PERSIST_PREVIEW_LINES])

        hint = (
            f"[Result too large ({size_kb:.1f} KB, {len(lines)} lines). "
            f"Full output saved to {filepath}. "
            f"You can use read to see the full result.]\n\n"
            f"Preview (first {PERSIST_PREVIEW_LINES} lines):\n{preview}"
        )
        return ToolMessage(content=hint, tool_call_id=msg.tool_call_id, name=msg.name)

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

    # ── Persist ─────────────────────────────────────────────
    def _persist_large_results(self, messages: list["Message"]) -> list["Message"]:
        """>30KB 结果落盘，替换为预览。"""
        return [self._persist_large_result(m) if isinstance(m, ToolMessage) else m for m in messages]

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
        """替换旧/重复工具结果为占位符，保留最近 N 个。"""
        tokens = self.estimate_tokens_raw(messages)
        if tokens / max(self.context_window, 1) < SNIP_THRESHOLD:
            return messages

        # 收集所有 ToolMessage 索引
        tool_indices = [i for i, m in enumerate(messages) if isinstance(m, ToolMessage)]
        if len(tool_indices) <= KEEP_RECENT_RESULTS:
            return messages

        snip_before = len(tool_indices) - KEEP_RECENT_RESULTS
        result = list(messages)
        for idx in tool_indices[:snip_before]:
            msg = result[idx]
            result[idx] = ToolMessage(
                content="[Content snipped - re-read if needed]",
                tool_call_id=msg.tool_call_id,
                name=msg.name,
            )
        return result

    # ── Microcompact ────────────────────────────────────────
    def _microcompact(self, messages: list["Message"]) -> list["Message"]:
        """不活跃时清理旧工具结果，替换为占位符（保留消息结构）。"""
        # 收集所有 ToolMessage 索引（跳过已 snip/cleared 的）
        SNIP_PLACEHOLDER = "[Content snipped - re-read if needed]"
        CLEARED_PLACEHOLDER = "[Old result cleared]"
        tool_indices = [
            i for i, m in enumerate(messages)
            if isinstance(m, ToolMessage)
            and m.content not in (SNIP_PLACEHOLDER, CLEARED_PLACEHOLDER)
        ]
        if len(tool_indices) <= KEEP_RECENT_RESULTS:
            return messages

        clear_count = len(tool_indices) - KEEP_RECENT_RESULTS
        result = list(messages)
        for idx in tool_indices[:clear_count]:
            msg = result[idx]
            result[idx] = ToolMessage(
                content=CLEARED_PLACEHOLDER,
                tool_call_id=msg.tool_call_id,
                name=msg.name,
            )
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
        """4 阶段压缩：Budget → Snip → Microcompact → Autocompact。
        Budget 始终运行（内部按 ratio 判断），后续三层仅在超阈值时触发。
        """
        tokens = self.estimate_tokens(state)

        # Budget — 始终运行，内部按 50%/70% ratio 决定是否截断
        state.messages = self._budget_truncate(state.messages)

        # Persist — >30KB 结果落盘 + 预览
        state.messages = self._persist_large_results(state.messages)

        if tokens < self.token_threshold:
            return state

        # Snip — 替换旧工具结果为占位符（>60% context）
        state.messages = self._snip_duplicates(state.messages)
        if self.estimate_tokens(state) < self.token_threshold:
            return state

        # Microcompact — 不活跃时清理旧结果（替换为占位符）
        now = time.time()
        if now - self._last_activity > MICROCOMPACT_IDLE_SECONDS:
            state.messages = self._microcompact(state.messages)
            self._last_activity = now
            if self.estimate_tokens(state) < self.token_threshold:
                return state

        # Autocompact — LLM 总结
        return await self._autocompact(state)
