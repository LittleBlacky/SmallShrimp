from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.agent import Agent
    
from ..core.message import Message, HumanMessage, AssistantMessage

@dataclass
class SessionState:

    session_id: str
    agent: Agent
    messages: list[Message] = field(default_factory=list)

    def add_user_message(self, content: str) -> None:
        self.messages.append(HumanMessage(content=content))

    def add_assistant_message(self, content: str) -> None:
        self.messages.append(AssistantMessage(content=content))

    def add_message(self, message: Message) -> None:
        self.messages.append(message)

    def build_messages(self) -> list[dict]:
        system_prompt = self._build_system_prompt()
        result = [{"role": "system", "content": system_prompt}]
        result.extend([msg.to_dict() for msg in self.messages])
        return result

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