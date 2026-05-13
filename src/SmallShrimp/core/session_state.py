from dataclasses import dataclass, field
from core.message import Message, HumanMessage, AssistantMessage
from core.agent import Agent

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
        agent_def = self.agent.agent_def
        return f"You are {agent_def.name}. {agent_def.description}"