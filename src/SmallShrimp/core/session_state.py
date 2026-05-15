from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..core.agent import Agent

from ..core.message import Message, HumanMessage, AssistantMessage, SystemMessage

@dataclass
class SessionState:

    session_id: str
    agent: "Agent"
    messages: list[Message] = field(default_factory=list)
    pending_reasoning_content: Optional[str] = None  # 待传回的 reasoning_content

    def add_user_message(self, content: str) -> None:
        self.messages.append(HumanMessage(content=content))

    def add_assistant_message(self, content: str) -> None:
        self.messages.append(AssistantMessage(content=content))

    def add_message(self, message: Message) -> None:
        self.messages.append(message)

    def _build_reasoning_message(self, pending_reasoning: str | None, thinking_strategy) -> dict | None:
        """根据 thinking_strategy 决定是否需要注入 reasoning_content 消息"""
        if not pending_reasoning:
            return None
        return thinking_strategy.prepare_reasoning_message(pending_reasoning)

    def build_messages(self, max_context_tokens: int | None = None) -> list[dict]:
        system_prompt = self._build_system_prompt()
        system_msg = SystemMessage(content=system_prompt)
        # 构建消息列表
        result: list[Message] = [system_msg]

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