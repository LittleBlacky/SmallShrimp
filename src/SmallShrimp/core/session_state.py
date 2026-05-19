from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..core.agent import Agent
    from ..core.context import SharedContext
    from ..core.events import EventSource

from ..core.message import Message, HumanMessage, AssistantMessage, SystemMessage

@dataclass
class SessionState:

    session_id: str
    agent: "Agent"
    messages: list[Message] = field(default_factory=list)
    pending_reasoning_content: Optional[str] = None  # 待传回的 reasoning_content
    source: Optional["EventSource"] = None
    shared_context: Optional["SharedContext"] = None

    def add_user_message(self, content: str) -> None:
        self.messages.append(HumanMessage(content=content))

    def add_assistant_message(self, content: str) -> None:
        self.messages.append(AssistantMessage(content=content))

    def add_message(self, message: Message) -> None:
        self.messages.append(message)
        # 持久化到历史记录
        if self.shared_context and self.shared_context.history_manager:
            self.shared_context.history_manager.append(
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
        chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 2 + other_chars / 4)

    def _build_system_prompt(self) -> str:
        """从 Agent 定义构建完整的系统提示。"""
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