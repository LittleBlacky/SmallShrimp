from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.agent import Agent
    from ..core.events import EventSource
    from ..core.history import HistoryManager
    from ..core.prompt_builder import PromptBuilder

from datetime import datetime

from ..core.message import Message, HumanMessage, AssistantMessage, SystemMessage


def _clip_utf8(text: str, max_bytes: int, *, from_end: bool = False) -> str:
    """按 UTF-8 字节数裁剪文本，避免截断多字节字符。"""
    if max_bytes <= 0:
        return ""
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return text
    clipped = data[-max_bytes:] if from_end else data[:max_bytes]
    return clipped.decode("utf-8", errors="ignore")


@dataclass
class SessionState:

    session_id: str
    agent: "Agent"
    messages: list[Message] = field(default_factory=list)
    pending_reasoning_content: Optional[str] = None  # 待传回的 reasoning_content
    source: Optional["EventSource"] = None
    history_manager: Optional["HistoryManager"] = None
    prompt_builder: Optional["PromptBuilder"] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())  # 会话创建时间（固化，保护 prompt 缓存）
    surfaced_memory_ids: set[str] = field(default_factory=set)
    session_memory_bytes: int = 0
    max_session_memory_bytes: int = 60 * 1024
    session_tool_result_bytes: int = 0
    max_session_tool_result_bytes: int = 256 * 1024

    def filter_new_memories(self, records: list[dict]) -> list[dict]:
        """按本会话记忆预算筛选尚未展示过的记忆。"""
        if self.session_memory_bytes >= self.max_session_memory_bytes:
            return []

        selected: list[dict] = []
        remaining = self.max_session_memory_bytes - self.session_memory_bytes
        for record in records:
            memory_id = str(record.get("id", ""))
            if memory_id and memory_id in self.surfaced_memory_ids:
                continue

            content_bytes = len(str(record.get("content", "")).encode("utf-8"))
            if content_bytes > remaining:
                continue

            selected.append(record)
            remaining -= content_bytes
        return selected

    def mark_memories_surfaced(self, records: list[dict]) -> None:
        """记录本会话已注入的记忆，避免重复召回。"""
        for record in records:
            memory_id = str(record.get("id", ""))
            if memory_id:
                self.surfaced_memory_ids.add(memory_id)
            self.session_memory_bytes += len(str(record.get("content", "")).encode("utf-8"))

    def budget_tool_result(self, tool_name: str, content: str) -> str:
        """按本会话工具结果预算裁剪写入上下文的工具输出。"""
        content_bytes = len(content.encode("utf-8"))
        if self.session_tool_result_bytes >= self.max_session_tool_result_bytes:
            return (
                f"[{tool_name} result omitted: session tool-result budget exhausted; "
                "rerun the tool with narrower arguments if full output is needed.]"
            )

        remaining = self.max_session_tool_result_bytes - self.session_tool_result_bytes
        if content_bytes <= remaining:
            self.session_tool_result_bytes += content_bytes
            return content

        notice = (
            f"\n\n[...tool result budgeted: {content_bytes - remaining} bytes truncated; "
            "rerun the tool with narrower arguments for full output...]\n\n"
        )
        notice_bytes = len(notice.encode("utf-8"))
        if remaining <= notice_bytes + 256:
            self.session_tool_result_bytes = self.max_session_tool_result_bytes
            return (
                f"[{tool_name} result omitted: only {remaining} bytes remained in "
                "session tool-result budget.]"
            )

        keep_bytes = remaining - notice_bytes
        head_bytes = keep_bytes // 2
        tail_bytes = keep_bytes - head_bytes
        budgeted = _clip_utf8(content, head_bytes) + notice + _clip_utf8(content, tail_bytes, from_end=True)
        self.session_tool_result_bytes += len(budgeted.encode("utf-8"))
        return budgeted

    def add_user_message(self, content: str) -> None:
        self.messages.append(HumanMessage(content=content))

    def add_assistant_message(self, content: str) -> None:
        self.messages.append(AssistantMessage(content=content))

    def add_message(self, message: Message) -> None:
        self.messages.append(message)
        # 持久化到历史记录
        if self.history_manager:
            self.history_manager.append(
                self.session_id, message.to_dict()
            )

    def _build_reasoning_message(self, pending_reasoning: str | None, thinking_strategy) -> dict | None:
        """根据 thinking_strategy 决定是否需要注入 reasoning_content 消息"""
        if not pending_reasoning:
            return None
        return thinking_strategy.prepare_reasoning_message(pending_reasoning)

    def build_messages(self, max_context_tokens: int | None = None) -> list[dict]:
        system_prompt = self._build_system_prompt()
        system_msg = SystemMessage(content=system_prompt)
        system_tokens = self._estimate_tokens(system_msg.content)

        # 构建消息列表
        result: list[Message] = [system_msg]

        # 如果有 context_window 限制，截断历史消息
        if max_context_tokens is not None:
            available_tokens = max_context_tokens - system_tokens - 100  # 留 100 token 缓冲

            for msg in self.messages:
                msg_tokens = self._estimate_tokens(msg.content)
                if available_tokens >= msg_tokens:
                    result.append(msg)
                    available_tokens -= msg_tokens
                else:
                    break
        else:
            result.extend(self.messages)

        # 根据 thinking_strategy 决定是否需要注入 reasoning_content 消息
        reasoning_msg = self._build_reasoning_message(
            self.pending_reasoning_content,
            self.agent.llm.thinking_strategy,
        )
        if reasoning_msg:
            result.insert(1, reasoning_msg)
            self.pending_reasoning_content = None  # 消费后清空

        # 统一转换为 dict
        return [msg.to_dict() if isinstance(msg, Message) else msg for msg in result]

    def _estimate_tokens(self, text: str) -> int:
        """估算 token 数量（粗略：英文约 4 字符/token，中文约 2 字符/token）。"""
        if not text:
            return 0
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 2 + other_chars / 4)

    def _build_system_prompt(self) -> str:
        """从 Agent 定义构建系统提示，优先使用 PromptBuilder。"""
        # 优先使用 PromptBuilder（多层提示词）
        if self.prompt_builder:
            return self.prompt_builder.build(self)

        # 回退：旧版简单构建
        agent_def = self.agent.agent_def

        parts = [
            f"You are {agent_def.name}.",
            agent_def.description,
        ]

        if agent_def.guidelines:
            parts.append("\n## Guidelines")
            for g in agent_def.guidelines:
                parts.append(f"- {g}")

        if agent_def.instructions:
            parts.append("\n## Instructions")
            for i in agent_def.instructions:
                parts.append(f"- {i}")

        return "\n".join(parts)
