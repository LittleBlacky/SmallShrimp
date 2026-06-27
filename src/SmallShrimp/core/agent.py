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
        if context_guard is None:
            from ..core.context_engine import create_context_engine
            engine_name = config.get("context_engine", "default")
            self.context_guard = create_context_engine(
                engine_name,
                token_threshold=token_threshold,
            )
        else:
            self.context_guard = context_guard
        # Pattern learner — 跨轮次记住操作经验
        from ..core.pattern_learning import PatternLearner
        self.pattern_learner = PatternLearner(
            state_path=str(config.data.get("workspace", "workspace")) + "/.cache/pattern_learning.json"
        )
        # Backward compat alias
        self.failure_learner = self.pattern_learner
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
        )
        return AgentSession(agent=self, state=state)

@dataclass
class AgentResult:
    """Structured result from run_once()."""
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    session_id: str = ""

@dataclass
class AgentSession:

    agent: Agent
    state: SessionState
    started_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        from ..core.tool_guardrails import ToolCallGuardrailController
        self._guardrail = ToolCallGuardrailController()
        self._turn_failures: list[dict] = []  # 本轮失败的工具调用
        self._turn_successes: list[dict] = []  # 本轮成功的工具调用
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
        from .turn_context import build_turn_context
        from .message_sanitizer import sanitize_user_message, sanitize_tool_result, repair_tool_call_args

        # Phase 1.1: TurnContext — 所有一次性初始化
        ctx = await build_turn_context(self, message)
        original_text = ctx.original_text

        # Phase 1.2: 有界迭代循环
        for _iteration in range(ctx.max_iterations):
            # 压缩上下文
            self.state = await self.agent.context_guard.check_and_compact(self.state)

            context_window = self.agent.agent_def.llm.get("context_window")
            messages = self.state.build_messages(max_context_tokens=context_window)
            schemas = self.agent.tool_registry.get_schemas(active_only=True)

            # Phase 1.2: 带重试的 LLM 调用
            response = await self._call_llm_with_retry(
                messages, schemas, self.state.pending_reasoning_content,
            )

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
                assistant_with_tools.tool_calls = repair_tool_call_args(response["tool_calls"])
                if reasoning:
                    assistant_with_tools.reasoning_content = reasoning
                self.state.add_message(assistant_with_tools)
                self.state.pending_reasoning_content = reasoning if should_store else None

                # 并行执行只读工具，串行执行写工具
                await self._execute_tool_calls(response["tool_calls"])
                continue

            # 非 tool_calls 的停止原因
            if finish_reason == "length":
                response["content"] = (response.get("content") or "") + (
                    "\n\n[响应因达到最大 token 限制而被截断]"
                )

            content = response.get("content") or ""

            # Phase 1.4: 空响应恢复 — 有 tool_calls 历史时 nudge 重试
            if not content.strip() and self._had_tool_calls_this_turn():
                nudge = "[System: 你刚执行了工具调用但返回了空响应。请继续分析或给出下一步操作。]"
                nudge_response = await self._call_llm_with_retry(
                    messages + [{"role": "user", "content": nudge}],
                    schemas,
                    self.state.pending_reasoning_content,
                )
                content = nudge_response.get("content") or ""

            assistant_msg = AssistantMessage(content=content)
            self.state.add_message(assistant_msg)

            # 可选验证器：检查回复质量
            capabilities = self.agent.agent_def.metadata.get("capabilities", {}) if hasattr(self.agent.agent_def, "metadata") else {}
            if capabilities.get("verifier"):
                from .verifier import verify_response, render_verification_hint
                v_result = await verify_response(original_text, content, self.agent.llm)
                if not v_result.passed:
                    hint = render_verification_hint(v_result)
                    # 注入 hint 让下一轮 LLM 看到（不重新生成本轮）
                    self.state.add_message(SystemMessage(content=hint))

            # 跨轮次模式学习 + 自动写 reflections
            notes = self.agent.pattern_learner.observe_turn(
                failures=self._turn_failures,
                successes=self._turn_successes,
            )
            for note in notes:
                self.state.add_message(SystemMessage(content=note))
                if self.agent.memory_manager:
                    try:
                        self.agent.memory_manager.store(
                            "reflections", note, importance=7, source="pattern_learner"
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
                        assistant_content=content,
                        session_id=self.session_id,
                    )
                except Exception:
                    pass

            return content

        # 迭代预算耗尽
        return "[达到最大工具调用轮次限制，请简化请求后重试。]"

    async def _call_llm_with_retry(
        self,
        messages: list,
        schemas: list,
        reasoning_content: str | None = None,
        max_retries: int = 3,
    ) -> dict:
        """带指数退避重试的 LLM 调用。"""
        import asyncio
        last_error = None
        for attempt in range(max_retries):
            try:
                return await self.agent.llm.chat(
                    messages,
                    tools=schemas,
                    reasoning_content=reasoning_content,
                )
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = 2 ** attempt + 0.5 * attempt
                    await asyncio.sleep(delay)
        raise last_error  # type: ignore[misc]

    def _had_tool_calls_this_turn(self) -> bool:
        """检查本轮是否有 tool_calls 历史。"""
        for m in reversed(self.state.messages):
            if isinstance(m, HumanMessage):
                break
            if isinstance(m, AssistantMessage) and m.tool_calls:
                return True
        return False

    async def _execute_tool_calls(self, tool_calls: list) -> None:
        """并行执行只读工具，串行执行写工具。含 guardrail 和三级权限检测。"""
        import asyncio
        from ..core.tool_guardrails import append_guardrail_warning, guardrail_synthetic_result, is_idempotent
        from ..tools.base import ToolPermission

        reads: list[tuple] = []
        writes: list[tuple] = []

        for tc in tool_calls:
            name = tc["function"]["name"]
            args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
            entry = (tc, name, args)

            # before_call 护栏预检
            decision = self._guardrail.before_call(name, args)
            if decision.is_block or decision.is_halt:
                self._check_guardrail_and_add(name, args, guardrail_synthetic_result(decision), False, tc)
                continue

            # 判断是否只读：优先使用工具自身的 is_action_read_only
            tool = self.agent.tool_registry.get(name)
            if tool and hasattr(tool, 'is_action_read_only'):
                read_only = tool.is_action_read_only(args)
            else:
                read_only = is_idempotent(name)

            if read_only:
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
            # 三级权限检查
            tool = self.agent.tool_registry.get(name)
            tool_perm = tool.permission if tool else ToolPermission.SAFE

            if tool_perm == ToolPermission.CONFIRM:
                # 需要确认的工具
                confirm_fn = getattr(self, '_confirm_fn', None)
                if confirm_fn:
                    approved = confirm_fn(f"确认执行 {name}？")
                    if approved is False:
                        self.state.add_message(ToolMessage(
                            content=f"Error: {name} denied by user.",
                            tool_call_id=tc["id"],
                            name=name,
                        ))
                        continue
                # 无确认回调 → 默认允许（非交互模式）

            # 旧权限系统兼容（PermissionChecker）
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
        from ..core.tool_guardrails import append_guardrail_warning, is_idempotent

        read_only = is_idempotent(name)
        decision = self._guardrail.after_call(
            name, args, result, failed=failed, is_read_only=read_only,
        )

        if decision.is_warning:
            result = append_guardrail_warning(result, decision)
        elif decision.is_halt:
            result = append_guardrail_warning(result, decision)

        # 记录成功/失败用于跨轮次学习
        if failed:
            self._turn_failures.append({"tool_name": name, "error": result})
        else:
            self._turn_successes.append({"tool_name": name, "detail": result[:200]})

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

    async def run_once(
        self,
        prompt: str,
        *,
        max_iterations: int = 20,
        agent_type: str | None = None,
    ) -> "AgentResult":
        """Direct-call mode for sub-agents. Returns AgentResult with text + token stats.

        Unlike chat(), this:
        - Skips history persistence (ephemeral session)
        - Uses filtered tool registry if agent_type is specified
        - Returns structured result instead of plain string
        """
        from .turn_context import build_turn_context
        from .message_sanitizer import repair_tool_call_args

        # Swap tool registry if agent_type specified
        original_registry = self.agent.tool_registry
        if agent_type:
            from .agent_types import filter_tools_for_type
            self.agent.tool_registry = filter_tools_for_type(original_registry, agent_type)

        try:
            ctx = await build_turn_context(self, prompt)
            total_input_tokens = 0
            total_output_tokens = 0
            final_content = ""

            for _iteration in range(max_iterations):
                self.state = await self.agent.context_guard.check_and_compact(self.state)
                context_window = self.agent.agent_def.llm.get("context_window")
                messages = self.state.build_messages(max_context_tokens=context_window)
                schemas = self.agent.tool_registry.get_schemas(active_only=True)

                response = await self._call_llm_with_retry(
                    messages, schemas, self.state.pending_reasoning_content,
                )

                # Accumulate tokens
                usage = response.get("usage", {})
                total_input_tokens += usage.get("prompt_tokens", 0)
                total_output_tokens += usage.get("completion_tokens", 0)

                reasoning = response.get("reasoning_content")
                should_store = response.get("should_store_reasoning", False)
                finish_reason = response.get("finish_reason", "stop")

                if finish_reason == "tool_calls" and response["tool_calls"]:
                    assistant_with_tools = AssistantMessage(content="")
                    assistant_with_tools.tool_calls = repair_tool_call_args(response["tool_calls"])
                    if reasoning:
                        assistant_with_tools.reasoning_content = reasoning
                    self.state.add_message(assistant_with_tools)
                    self.state.pending_reasoning_content = reasoning if should_store else None
                    await self._execute_tool_calls(response["tool_calls"])
                    continue

                content = response.get("content") or ""
                if finish_reason == "length":
                    content += "\n\n[响应因达到最大 token 限制而被截断]"

                assistant_msg = AssistantMessage(content=content)
                self.state.add_message(assistant_msg)
                final_content = content
                break

            return AgentResult(
                text=final_content,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                session_id=self.session_id,
            )
        finally:
            # Always restore original registry
            self.agent.tool_registry = original_registry
