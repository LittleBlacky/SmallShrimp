
from __future__ import annotations

"""Context guard for proactive context window management.

4-tier compaction (zero-cost first):
  Tier 1 (Offload):    Persist large tool results to disk, keep summary+path in message
  Tier 2 (Snip):       Replace stale/duplicate reads with placeholders
  Tier 3 (Microcompact): Drop old tool results after inactivity
  Tier 4 (Autocompact): LLM summary (API call)
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
import os
import time
import uuid

from litellm import token_counter

if TYPE_CHECKING:
    from .session_state import SessionState

from .message import Message, ToolMessage, HumanMessage

OFFLOAD_SIZE_THRESHOLD = 10000  # chars: results larger than this get offloaded to disk
OFFLOAD_HEAD_CHARS = 3000       # chars to keep as inline summary
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

    # ── Offload ─────────────────────────────────────────────
    def _offload_large_results(self, messages: list["Message"]) -> list["Message"]:
        """大工具结果落盘，消息中只保留摘要 + read() 路径（可恢复）。"""
        tokens = self.estimate_tokens_raw(messages)
        ratio = self._fill_ratio(tokens)

        # 根据上下文压力设置阈值
        if ratio < 0.5:
            threshold = OFFLOAD_SIZE_THRESHOLD * 3
        elif ratio < 0.7:
            threshold = OFFLOAD_SIZE_THRESHOLD
        else:
            threshold = OFFLOAD_SIZE_THRESHOLD // 2

        result: list[Message] = []
        for msg in messages:
            if isinstance(msg, ToolMessage) and msg.content and len(msg.content) > threshold:
                result.append(self._offload_one(msg))
            else:
                result.append(msg)
        return result

    def _offload_one(self, msg: ToolMessage) -> ToolMessage:
        """保存完整结果到磁盘，返回摘要消息。"""
        content = msg.content or ""
        tool_name = msg.name or "unknown"
        tool_id = msg.tool_call_id or uuid.uuid4().hex[:8]

        os.makedirs(self.offload_dir, exist_ok=True)
        filename = f"{tool_name}_{tool_id}.txt"
        filepath = os.path.join(self.offload_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        # 按工具类型生成摘要
        summary = self._summarize(msg, max_chars=OFFLOAD_HEAD_CHARS)
        hint = (
            f"[Offloaded: {len(content)} chars → {filepath}]\n"
            f"Use read(path=\"{filepath}\") to view full result.\n\n"
            f"{summary}"
        )
        return ToolMessage(content=hint, tool_call_id=msg.tool_call_id, name=msg.name)

    # ── summarize helpers ────────────────────────────────

    @staticmethod
    def _summarize(msg: ToolMessage, max_chars: int) -> str:
        """按工具类型生成摘要。"""
        name = msg.name or ""
        content = msg.content or ""

        if name in ("read", "webread"):
            return ContextGuard._summarize_readlike(content, max_chars)
        elif name == "glob":
            return ContextGuard._summarize_glob(content, max_chars)
        elif name == "grep":
            return ContextGuard._summarize_grep(content, max_chars)
        elif name == "websearch":
            return ContextGuard._summarize_websearch(content, max_chars)
        else:
            return content[:max_chars] + ("..." if len(content) > max_chars else "")

    @staticmethod
    def _summarize_readlike(content: str, max_chars: int) -> str:
        """read/webread: 保留行范围信息 + 开头摘要。"""
        lines_header = ""
        body = content
        if content.startswith("[Lines ") or content.startswith("[Line "):
            end = content.find("]\n")
            if end != -1:
                lines_header = content[:end + 1] + "\n"
                body = content[end + 2:]

        # 取开头 + 结尾各一半
        half = max_chars // 2
        head = body[:half]
        tail = body[-half:] if len(body) > half else ""
        sep = "\n...\n" if tail else ""
        return lines_header + head + sep + tail

    @staticmethod
    def _summarize_glob(content: str, max_chars: int) -> str:
        """glob: 列出文件数量 + 前几个。"""
        lines = content.strip().split("\n")
        total = len(lines)
        kept = []
        for line in lines:
            if len("\n".join(kept + [line])) > max_chars:
                kept.append(f"... and {total - len(kept)} more files")
                break
            kept.append(line)
        return "\n".join(kept)

    @staticmethod
    def _summarize_grep(content: str, max_chars: int) -> str:
        """grep: 匹配数量 + 前几条。"""
        lines = content.strip().split("\n")
        total = len(lines)
        kept = []
        for line in lines:
            if len("\n".join(kept + [line])) > max_chars:
                kept.append(f"... and {total - len(kept)} more matches")
                break
            kept.append(line)
        return "\n".join(kept)

    @staticmethod
    def _summarize_websearch(content: str, max_chars: int) -> str:
        """websearch: 结果数量 + 前几条。"""
        entries = content.split("\n\n")
        total = len(entries)
        kept = []
        for entry in entries:
            if len("\n\n".join(kept + [entry])) > max_chars:
                kept.append(f"... and {total - len(kept)} more results")
                break
            kept.append(entry)
        return "\n\n".join(kept)

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
        """4 阶段压缩：Offload 落盘 → Snip 去重 → Microcompact 清旧 → Autocompact 总结。"""
        tokens = self.estimate_tokens(state)

        # 未超限
        if tokens < self.token_threshold:
            return state

        # Offload — 大结果落盘（无损：read 可恢复）
        state.messages = self._offload_large_results(state.messages)
        if self.estimate_tokens(state) < self.token_threshold:
            return state

        # Snip — 替换重复读取（无损：保留最后一次完整内容）
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
