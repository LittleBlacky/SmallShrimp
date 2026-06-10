from __future__ import annotations
import json
import os
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
        memory_manager: "Any | None" = None,
    ) -> None:
        self.agent_def = agent_def
        self.config = config
        self.memory_manager = memory_manager
        self.llm: "LLMProvider" = self._create_llm()
        self.history_manager = history_manager
        self.prompt_builder = prompt_builder
        if agent_def.tools:
            from ..tools.registry import ToolRegistry
            self.tool_registry = ToolRegistry()
            for name in agent_def.tools:
                t = tool_registry.get(name)
                if t:
                    self.tool_registry.register(t)
        else:
            self.tool_registry = tool_registry
        # 从 agent_def 获取 context_window 的 80% 作为压缩阈值
        context_window = agent_def.llm.get("context_window", 200000)
        token_threshold = int(context_window * 0.8)
        from ..core.context_guard import ContextGuard
        self.context_guard = ContextGuard(token_threshold=token_threshold) if context_guard is None else context_guard
        # Failure learner — 跨轮次记住失败模式
        from ..core.failure_learning import FailureLearner
        self.failure_learner = FailureLearner(
            state_path=str(config.data.get("workspace", "workspace")) + "/.cache/failure_learning.json"
        )
        # Permission mode
        from ..core.permissions import PermissionMode, PermissionChecker
        mode_str = agent_def.llm.get("permission_mode", "default")
        perm_mode = PermissionMode(mode_str) if mode_str in PermissionMode.__members__ else PermissionMode.DEFAULT
        self.permission_checker = PermissionChecker(perm_mode)
        # Trust manager — Layer 1 defense
        from ..core.trust import TrustManager
        self.trust_manager = TrustManager(
            state_path=str(config.data.get("workspace", "workspace")) + "/.cache/trust.json"
        )
        # MCP manager（自注册热重载）
        from ..core.mcp import McpManager
        self.mcp_manager = McpManager(config=config, tool_registry=self.tool_registry)
        self._mcp_registered = False

        # Agent 自身热重载：LLM + Permission
        config.on_change(lambda data: self._on_config_reload(data))

    def _on_config_reload(self, new_data: dict):
        """配置热重载：重建 LLM 和权限。"""
        self.llm = self._create_llm()
        mode_str = new_data.get("permission_mode") or self.agent_def.llm.get("permission_mode", "default")
        from ..core.permissions import PermissionMode
        if mode_str in PermissionMode.__members__:
            self.permission_checker.mode = PermissionMode(mode_str)

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

    def __post_init__(self):
        from ..core.tool_guardrails import ToolGuardrailController
        self._guardrail = ToolGuardrailController()
        self._turn_failures: list[dict] = []  # 本轮失败的工具调用
        self._trust_checked = False  # Trust Dialog 是否已检查
        self._on_tool_call = None  # 工具调用回调 (CLI 显示用)
        self._on_thinking = None  # 思考内容回调
        self._confirm_fn = None  # 确认回调

        # 初始化 MemoryProvider 会话级缓存快照
        if self.agent.memory_manager:
            self.agent.memory_manager.initialize(self.state.session_id)

    @property
    def session_id(self) -> str:
        return self.state.session_id

    def set_confirm_fn(self, fn):
        """注入外部确认回调。fn(message) → True/False/None."""
        self._confirm_fn = fn

    def set_on_tool_call(self, fn):
        """注入工具调用回调。fn(tool_name, args, result, failed)."""
        self._on_tool_call = fn

    def set_on_thinking(self, fn):
        """注入思考内容回调。fn(reasoning_text)."""
        self._on_thinking = fn
        
    async def chat(self, message: str) -> str:
        """发送消息，支持工具调用循环。"""
        # MCP 懒初始化（首次 chat 时连接）
        if not self.agent._mcp_registered:
            self.agent._mcp_registered = True
            from ..core.mcp import register_mcp_tools
            await register_mcp_tools(self.agent.mcp_manager, self.agent.tool_registry)

        # 检测用户纠正信号（关键词 + 结构分析）
        from ..core.correction import detect_correction_combined, render_correction_hint, CorrectionConfidence
        # 获取上一条 assistant 消息内容作为结构分析上下文
        prev_assistant = ""
        for m in reversed(self.state.messages):
            if isinstance(m, AssistantMessage) and m.content:
                prev_assistant = m.content or ""
                break
        original_text = message  # 保存原始文本供 prefetch/auto-write 用
        correction = detect_correction_combined(original_text, prev_assistant)
        if correction:
            hint = render_correction_hint(correction)
            message = f"{hint}\n\n---\n\n{message}"
            # HIGH 置信度纠正 → 自动写 profile
            if correction.confidence == CorrectionConfidence.HIGH and self.agent.memory_manager:
                try:
                    self.agent.memory_manager.remember_profile(
                        correction.phrase, source="correction"
                    )
                except Exception:
                    pass

        # 添加用户消息
        user_msg = HumanMessage(content=message)
        self.state.add_message(user_msg)

        # 重置本轮 guardrail 计数器
        self._guardrail.reset()
        self._turn_failures.clear()

        # Trust Dialog — 首次进入工作区检查信任
        if not self._trust_checked:
            self._trust_checked = True
            cwd = os.getcwd()
            if not self.agent.trust_manager.is_trusted(cwd):
                warnings = self.agent.trust_manager.scan_dangerous(cwd)
                if warnings and (confirm_fn := getattr(self, '_confirm_fn', None)):
                    approved = confirm_fn(
                        f"Trust directory '{cwd}'?\nDetected: {', '.join(warnings[:5])}"
                    )
                    if approved:
                        self.agent.trust_manager.trust(cwd)

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

            # 回调 CLI 显示思考内容
            if reasoning and self._on_thinking:
                try:
                    self._on_thinking(reasoning)
                except Exception:
                    pass

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

                # 并行执行只读工具，串行执行写工具
                await self._execute_tool_calls(response["tool_calls"])

                # 继续循环
                continue

            # 非 tool_calls 的停止原因（stop / length / content_filter）
            if finish_reason == "length":
                response["content"] = (response.get("content") or "") + (
                    "\n\n[响应因达到最大 token 限制而被截断]"
                )

            assistant_msg = AssistantMessage(content=response["content"] or "")
            self.state.add_message(assistant_msg)

            # 跨轮次失败学习 + 自动写 reflections
            notes = self.agent.failure_learner.observe_turn(self._turn_failures)
            for note in notes:
                from ..core.message import SystemMessage
                self.state.add_message(SystemMessage(content=note))
                if self.agent.memory_manager:
                    try:
                        self.agent.memory_manager.remember_reflection(
                            note, importance=7, source="failure_learner"
                        )
                    except Exception:
                        pass

            if self.agent.history_manager:
                self.agent.history_manager.save(self.session_id, self.state.messages)

            # 持久化本轮到 memory sessions 层
            if self.agent.memory_manager:
                try:
                    self.agent.memory_manager.sync_turn(
                        user_content=original_text,
                        assistant_content=response["content"] or "",
                        session_id=self.session_id,
                    )
                except Exception:
                    pass

            return response["content"] or ""

    async def _execute_tool_calls(self, tool_calls: list) -> None:
        """并行执行只读工具，串行执行写工具。含 guardrail 检测。"""
        import asyncio
        from ..core.tool_guardrails import append_guardrail_warning

        READONLY_TOOLS = {"read", "glob", "grep", "websearch", "webread", "skill"}
        reads: list[tuple] = []
        writes: list[tuple] = []

        for tc in tool_calls:
            name = tc["function"]["name"]
            args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
            entry = (tc, name, args)
            if name in READONLY_TOOLS:
                reads.append(entry)
            else:
                writes.append(entry)

        # 并行执行只读工具
        if reads:
            async def _run_read(tc, name, args):
                try:
                    result = await self.agent.tool_registry.execute_tool(name, **args)
                    return (tc, name, args, result, False)
                except Exception as e:
                    return (tc, name, args, f"Error: {e}", True)
            results = await asyncio.gather(*(_run_read(*r) for r in reads))
            for tc, name, args, result, failed in results:
                self._check_guardrail_and_add(name, args, result, failed, tc)

        # 串行执行写工具
        for tc, name, args in writes:
            # 权限检查
            perm = self.agent.permission_checker.check(name, args)
            if perm.needs_confirmation:
                confirm_fn = getattr(self, '_confirm_fn', None)
                if confirm_fn:
                    approved = confirm_fn(perm.message)
                    if approved is False:
                        self.state.add_message(ToolMessage(
                            content=f"Error: {name} denied by user.",
                            tool_call_id=tc["id"],
                            name=name,
                        ))
                        continue
                    if approved is True:
                        path = args.get("path", args.get("file_path", ""))
                        self.agent.permission_checker.confirm_path(path)
                # 无确认回调 → 默认允许（非交互模式）
            elif perm.is_denied:
                self.state.add_message(ToolMessage(
                    content=f"Error: {perm.message}",
                    tool_call_id=tc["id"],
                    name=name,
                ))
                continue

            try:
                execute_args = args
                if name == "recall_memory":
                    execute_args = {**args, "_session_state": self.state}
                result = await self.agent.tool_registry.execute_tool(name, **execute_args)
                failed = result.startswith("Error:")
            except Exception as e:
                result = f"Error: {e}"
                failed = True
            self._check_guardrail_and_add(name, args, result, failed, tc)

    def _check_guardrail_and_add(
        self, name: str, args: dict, result: str, failed: bool, tc: dict
    ) -> None:
        """Guardrail 检查 + 添加 ToolMessage。"""
        from ..core.tool_guardrails import append_guardrail_warning

        is_read_only = name in {"read", "glob", "grep", "websearch", "webread", "skill"}
        decision = self._guardrail.after_call(
            name, args, result, failed=failed, is_read_only=is_read_only,
        )

        if decision.is_warning:
            result = append_guardrail_warning(result, decision)

        # 记录失败用于跨轮次学习
        if failed:
            self._turn_failures.append({"tool_name": name, "error": result})

        # 回调 CLI 显示
        if self._on_tool_call:
            try:
                self._on_tool_call(name, args, result, failed)
            except Exception:
                pass

        budgeted_result = self.state.budget_tool_result(name, result)
        self.state.add_message(ToolMessage(
            content=budgeted_result,
            tool_call_id=tc["id"],
            name=name,
        ))
