import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING
from ..core.session_state import SessionState
from ..core.message import HumanMessage, AssistantMessage

if TYPE_CHECKING:
    from provider.llm.base import LLMProvider
    from utils.def_loader import AgentDef
    from utils.config import Config

class Agent:

    def __init__(self, agent_def: "AgentDef", config: "Config") -> None:
        self.agent_def = agent_def
        self.config = config
        self.llm: "LLMProvider" = self._create_llm()

    def _create_llm(self) -> "LLMProvider":
        from ..provider.llm.base import LLMProvider, LLMConfig

        config_llm = self.config.get_llm_config()

        merged = {
            "provider": self.agent_def.llm.get("provider"),
            "model": self.agent_def.llm.get("model"),
            "api_key": config_llm.get("api_key"),
            "api_base": config_llm.get("api_base"),
            "temperature": self.agent_def.llm.get("temperature", 0.7),
        }

        return LLMProvider(LLMConfig(**merged))

    def new_session(self, session_id: str | None = None) -> "AgentSession":
        session_id = session_id or str(uuid.uuid4())
        state = SessionState(
            session_id=session_id,
            agent=self,
            messages=[],
        )
        return AgentSession(agent=self, state=state)

@dataclass
class AgentSession:

    agent: Agent
    state: SessionState
    started_at: datetime = field(default_factory=datetime.now)

    @property
    def session_id(self) -> str:
        return self.state.session_id
        
    async def chat(self, message: str) -> str:
        user_msg = HumanMessage(content=message)
        self.state.add_message(user_msg)
        messages = self.state.build_messages()
        response = await self.agent.llm.chat(messages)
        assistant_msg = AssistantMessage(content=response)
        self.state.add_message(assistant_msg)
        return response