from __future__ import annotations
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from ..core.session_state import SessionState
from ..core.message import HumanMessage, AssistantMessage, ToolMessage

if TYPE_CHECKING:
    from provider.llm.base import LLMProvider
    from utils.def_loader import AgentDef
    from utils.config import Config
    from tools.registry import ToolRegistry
    from core.history import HistoryManager
    
class Agent:

    def __init__(
        self,
        agent_def: "AgentDef",
        config: "Config",
        tool_registry: "ToolRegistry",
        history_manager: "HistoryManager",
        prompt_builder: "PromptBuilder | None" = None,
        context_guard: "ContextGuard | None" = None,
    ) -> None:
        self.agent_def = agent_def
        self.config = config
        self.llm: "LLMProvider" = self._create_llm()
        self.tool_registry = tool_registry
        self.history_manager = history_manager
        self.prompt_builder = prompt_builder
        # 从 agent_def 获取 context_window 的 80% 作为压缩阈值
        context_window = agent_def.llm.get("context_window", 200000)
        token_threshold = int(context_window * 0.8)
        from ..core.context_guard import ContextGuard
        self.context_guard = ContextGuard(token_threshold=token_threshold) if context_guard is None else context_guard

    def _create_llm(self) -> "LLMProvider":
        from ..provider.llm.base import LLMProvider, LLMConfig

        # 从 agent_def 获取 provider，如果没有就用默认 provider
        provider_name = self.agent_def.llm.get("provider") or self.config.get_default_provider()
        provider_config = self.config.get_provider_config(provider_name)

        merged = {
            "provider": provider_name,
            "model": self.agent_def.llm.get("model"),
            "api_key": provider_config.get("api_key"),
            "api_base": provider_config.get("api_base"),
            "temperature": self.agent_def.llm.get("temperature", 0.7),
            "max_tokens": self.agent_def.llm.get("max_tokens", 4096),
        }

        return LLMProvider(LLMConfig(**merged))

    def new_session(self, session_id: Optional[str] = None, source: str | None = None) -> "AgentSession":
        session_id = session_id or str(uuid.uuid4())
        state = SessionState(
            session_id=session_id,
            agent=self,
            messages=[],
            history_manager=self.history_manager,
            prompt_builder=self.prompt_builder,
            source=source,
        )
        return AgentSession(agent=self, state=state)

    def resume_session(self, session_id: str) -> "AgentSession":
        """恢复已有会话。"""
        messages = []
        if self.history_manager:
            messages = self.history_manager.load(session_id)
        state = SessionState(
            session_id=session_id,
            agent=self,
            messages=messages,
            shared_context=getattr(self, 'shared_context', None),
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
        """发送消息，支持工具调用循环。"""
        # 添加用户消息
        user_msg = HumanMessage(content=message)
        self.state.add_message(user_msg)

        # 循环：直到 LLM 返回普通回复
        while True:
            # 检查并压缩上下文
            self.state = await self.agent.context_guard.check_and_compact(self.state)

            context_window = self.agent.agent_def.llm.get("context_window")
            messages = self.state.build_messages(max_context_tokens=context_window)

            # 获取工具 schema
            schemas = self.agent.tool_registry.get_schemas()

            # 调用 LLM（带 tools 和 pending_reasoning_content）
            response = await self.agent.llm.chat(
                messages,
                tools=schemas,
                reasoning_content=self.state.pending_reasoning_content,
            )

            # 解析 LLM 返回
            reasoning = response.get("reasoning_content")
            should_store = response.get("should_store_reasoning", False)
            finish_reason = response.get("finish_reason", "stop")

            if finish_reason == "tool_calls" and response["tool_calls"]:

                # 保存 assistant 消息
                assistant_with_tools = AssistantMessage(content="")
                assistant_with_tools.tool_calls = response["tool_calls"]
                # 有些 provider 需要把 reasoning_content 嵌入到 assistant 消息中
                if reasoning:
                    assistant_with_tools.reasoning_content = reasoning
                self.state.add_message(assistant_with_tools)

                # 由 thinking_strategy 决定是否保存 reasoning_content 到 pending
                self.state.pending_reasoning_content = reasoning if should_store else None

                for tool_call in response["tool_calls"]:
                    tool_name = tool_call["function"]["name"]
                    tool_args = json.loads(tool_call["function"]["arguments"]) if isinstance(tool_call["function"]["arguments"], str) else tool_call["function"]["arguments"]

                    # 执行工具
                    tool_result = await self.agent.tool_registry.execute_tool(
                        tool_name, **tool_args
                    )

                    # 添加工具结果消息
                    tool_msg = ToolMessage(
                        content=tool_result,
                        tool_call_id=tool_call["id"],
                        name=tool_name
                    )
                    self.state.add_message(tool_msg)

                # 继续循环
                continue

            # 非 tool_calls 的停止原因（stop / length / content_filter）
            if finish_reason == "length":
                response["content"] = (response.get("content") or "") + (
                    "\n\n[响应因达到最大 token 限制而被截断]"
                )

            assistant_msg = AssistantMessage(content=response["content"] or "")
            self.state.add_message(assistant_msg)

            if self.agent.history_manager:
                self.agent.history_manager.save(self.session_id, self.state.messages)
            return response["content"] or ""