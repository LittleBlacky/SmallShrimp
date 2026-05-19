
from __future__ import annotations

"""Context guard for proactive context window management.

4-tier compaction (zero-cost first):
  Tier 1 (Budget):     Progressive tool result truncation
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

MAX_TOOL_RESULT_CHARS = 10000
BUDGET_TIER1_CHARS = 30000   # 50-70% context full
BUDGET_TIER2_CHARS = 15000   # >70% full
MICROCOMPACT_IDLE_SECONDS = 60  # inactivity before microcompact

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

    def __init__(self, token_threshold: int = 160000, context_window: int = 200000):
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
        """渐进截断工具结果：50-70% → 30KB, >70% → 15KB。"""
        tokens = self.estimate_tokens_raw(messages)
        ratio = self._fill_ratio(tokens)

        if ratio < 0.5:
            limit = MAX_TOOL_RESULT_CHARS
        elif ratio < 0.7:
            limit = BUDGET_TIER1_CHARS
        else:
            limit = BUDGET_TIER2_CHARS

        truncated = []
        for msg in messages:
            if not isinstance(msg, ToolMessage) or len(msg.content) <= limit:
                truncated.append(msg)
                continue

            if msg.name in ("read", "webread"):
                truncated.append(self._truncate_readlike(msg, limit))
            elif msg.name == "glob":
                truncated.append(self._truncate_glob(msg, limit))
            elif msg.name == "grep":
                truncated.append(self._truncate_grep(msg, limit))
            elif msg.name == "websearch":
                truncated.append(self._truncate_websearch(msg, limit))
            else:
                truncated.append(self._truncate_default(msg, limit))
        return truncated

    # ── 各工具截断策略 ──────────────────────────────────────

    @staticmethod
    def _truncate_readlike(msg: ToolMessage, limit: int) -> ToolMessage:
        """read/webread: 保留头尾 + 行范围提示。"""
        half = limit // 2
        head = msg.content[:half]
        tail = msg.content[-half:]
        # 解析 [Lines X-Y of Z] 头部
        if msg.content.startswith("[Lines "):
            try:
                end = msg.content.index("]")
                inner = msg.content[7:end]  # e.g. "0-199 of 200"
                range_part, _, total_str = inner.partition(" of ")
                total = int(total_str)
                head_lines = head.count("\n") + 1
                tail_lines = tail.count("\n") + 1
                tail_start = total - tail_lines
                info = (
                    f", missing lines {head_lines}-{tail_start - 1} of {total}. "
                    f"Use read(path, offset={head_lines}, limit=N)"
                )
            except Exception:
                info = f", showing first and last {len(head)}"
        else:
            info = f", showing first and last {len(head)}"
        return ToolMessage(
            content=f"{head}\n\n...[{len(msg.content)} chars]{info}\n\n{tail}",
            tool_call_id=msg.tool_call_id,
            name=msg.name,
        )

    @staticmethod
    def _truncate_glob(msg: ToolMessage, limit: int) -> ToolMessage:
        """glob: 按行保留所有文件名，中间省略。"""
        lines = msg.content.split("\n")
        if len(lines) <= 2:
            return msg
        half = max(2, limit // len(lines[0]) if lines[0] else limit // 20)
        head = lines[:half]
        tail = lines[-half:]
        omitted = len(lines) - half * 2
        new_content = "\n".join(head) + f"\n...[{omitted} files omitted]\n" + "\n".join(tail)
        return ToolMessage(
            content=new_content,
            tool_call_id=msg.tool_call_id,
            name=msg.name,
        )

    @staticmethod
    def _truncate_grep(msg: ToolMessage, limit: int) -> ToolMessage:
        """grep: 每条匹配独立，保留前 N 条和后 N 条。"""
        lines = msg.content.split("\n")
        if len(lines) <= 3:
            return msg
        keep = max(3, min(50, limit // 200))
        head = lines[:keep]
        tail = lines[-keep:]
        omitted = len(lines) - keep * 2
        new_content = "\n".join(head) + f"\n...[{omitted} matches omitted]\n" + "\n".join(tail)
        return ToolMessage(
            content=new_content,
            tool_call_id=msg.tool_call_id,
            name=msg.name,
        )

    @staticmethod
    def _truncate_websearch(msg: ToolMessage, limit: int) -> ToolMessage:
        """websearch: 保留前几条完整结果，省略中间。"""
        # websearch 结果格式：1. **title**\n   url\n   snippet\n\n
        entries = msg.content.split("\n\n")
        if len(entries) <= 4:
            return msg
        keep = max(2, len(entries) // 3)
        head = entries[:keep]
        tail = entries[-1:]
        omitted = len(entries) - keep - 1
        new_content = "\n\n".join(head) + f"\n\n...[{omitted} results omitted]\n\n" + "\n\n".join(tail)
        return ToolMessage(
            content=new_content,
            tool_call_id=msg.tool_call_id,
            name=msg.name,
        )

    @staticmethod
    def _truncate_default(msg: ToolMessage, limit: int) -> ToolMessage:
        """默认: 保留头尾。"""
        half = limit // 2
        head = msg.content[:half]
        tail = msg.content[-half:]
        return ToolMessage(
            content=f"{head}\n\n...[{len(msg.content)} chars, showing first and last {half}]\n\n{tail}",
            tool_call_id=msg.tool_call_id,
            name=msg.name,
        )

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
        """4 阶段压缩：零成本优先。"""
        tokens = self.estimate_tokens(state)

        # 未超限
        if tokens < self.token_threshold:
            return state

        # Budget — 渐进截断工具结果
        state.messages = self._budget_truncate(state.messages)
        if self.estimate_tokens(state) < self.token_threshold:
            return state

        # Snip — 替换重复读取
        state.messages = self._snip_duplicates(state.messages)
        if self.estimate_tokens(state) < self.token_threshold:
            return state

        # Microcompact — 清理旧工具结果
        now = time.time()
        if now - self._last_activity > MICROCOMPACT_IDLE_SECONDS:
            state.messages = self._microcompact(state.messages)
            self._last_activity = now
            if self.estimate_tokens(state) < self.token_threshold:
                return state

        # Autocompact — LLM 总结
        return await self._autocompact(state)
