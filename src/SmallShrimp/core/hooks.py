from __future__ import annotations

from copy import deepcopy
import inspect
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Literal

logger = logging.getLogger(__name__)

HookAction = Literal["observe", "modify", "skip", "abort", "fork", "enqueue"]


class HookPoint(str, Enum):
    SESSION_START = "session.start"
    SESSION_END = "session.end"
    MESSAGE_RECEIVED = "message.received"
    CONTEXT_BUILT = "context.built"
    BEFORE_LLM_CALL = "llm.before_call"
    AFTER_LLM_CALL = "llm.after_call"
    BEFORE_TOOL_CALL = "tool.before_call"
    AFTER_TOOL_CALL = "tool.after_call"
    BEFORE_RESPONSE = "response.before"
    AFTER_RESPONSE = "response.after"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    FORK_CREATED = "fork.created"
    SUBAGENT_STARTED = "subagent.started"
    SUBAGENT_COMPLETED = "subagent.completed"
    ERROR = "error"


@dataclass(frozen=True)
class HookPermissions:
    observe: bool = True
    modify_message: bool = False
    modify_llm_request: bool = False
    modify_llm_response: bool = False
    modify_tool_call: bool = False
    modify_tool_result: bool = False
    modify_response: bool = False
    skip_tool: bool = False
    abort_turn: bool = False
    fork_agent: bool = False
    enqueue_task: bool = False
    write_files: bool = False
    network: bool = False


@dataclass
class HookContext:
    hook_point: HookPoint
    session_id: str
    agent_id: str
    parent_session_id: str | None = None
    source: str | None = None
    state: Any | None = None
    turn_id: str | None = None
    user_message: str | None = None
    assistant_response: str | None = None
    messages: list[dict[str, Any]] | None = None
    tools: list[dict[str, Any]] | None = None
    llm_response: dict[str, Any] | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: str | None = None
    failed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HookResult:
    action: HookAction = "observe"
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""

    @classmethod
    def observe(cls, message: str = "") -> HookResult:
        return cls(action="observe", message=message)

    @classmethod
    def modify(cls, data: dict[str, Any], message: str = "") -> HookResult:
        return cls(action="modify", data=data, message=message)

    @classmethod
    def skip(cls, message: str = "") -> HookResult:
        return cls(action="skip", message=message)

    @classmethod
    def abort(cls, message: str) -> HookResult:
        return cls(action="abort", message=message)

    @classmethod
    def fork(cls, data: dict[str, Any], message: str = "") -> HookResult:
        return cls(action="fork", data=data, message=message)

    @classmethod
    def enqueue(cls, data: dict[str, Any], message: str = "") -> HookResult:
        return cls(action="enqueue", data=data, message=message)


HookHandler = Callable[[HookContext], HookResult | Awaitable[HookResult]]


@dataclass
class RegisteredHook:
    handler: HookHandler
    point: HookPoint
    name: str
    priority: int = 500
    permissions: HookPermissions = field(default_factory=HookPermissions)
    critical: bool = False
    source: str = "code"


class HookManager:
    def __init__(self) -> None:
        self._hooks: dict[HookPoint, list[RegisteredHook]] = {point: [] for point in HookPoint}

    def register(
        self,
        point: HookPoint | str,
        handler: HookHandler,
        *,
        name: str = "",
        priority: int = 500,
        permissions: HookPermissions | None = None,
        critical: bool = False,
        source: str = "code",
    ) -> Callable[[], None]:
        hook_point = HookPoint(point)
        registered = RegisteredHook(
            handler=handler,
            point=hook_point,
            name=name or getattr(handler, "__name__", "hook"),
            priority=priority,
            permissions=permissions or HookPermissions(),
            critical=critical,
            source=source,
        )
        self._hooks[hook_point].append(registered)
        self._hooks[hook_point].sort(key=lambda hook: hook.priority)

        def unsubscribe() -> None:
            if registered in self._hooks[hook_point]:
                self._hooks[hook_point].remove(registered)

        return unsubscribe

    def list_hooks(self, point: HookPoint | str | None = None) -> list[RegisteredHook]:
        if point is None:
            return [hook for hooks in self._hooks.values() for hook in hooks]
        return list(self._hooks[HookPoint(point)])

    async def run(self, context: HookContext) -> HookResult:
        final = HookResult.observe()
        for hook in list(self._hooks.get(context.hook_point, [])):
            try:
                result = hook.handler(self._snapshot_context(context))
                if inspect.isawaitable(result):
                    result = await result
                if not isinstance(result, HookResult):
                    result = HookResult.observe()
                result = self._enforce_permissions(hook, context, result)
            except Exception:
                logger.exception("Hook %s failed at %s", hook.name, context.hook_point.value)
                if hook.critical:
                    raise
                continue

            if result.action == "modify":
                final = self._merge_modify(final, result)
            elif result.action in ("skip", "abort", "fork", "enqueue"):
                return result
            elif final.action == "observe":
                final = result
        return final

    def _snapshot_context(self, context: HookContext) -> HookContext:
        return HookContext(
            hook_point=context.hook_point,
            session_id=context.session_id,
            agent_id=context.agent_id,
            parent_session_id=context.parent_session_id,
            source=context.source,
            state=context.state,
            turn_id=context.turn_id,
            user_message=context.user_message,
            assistant_response=context.assistant_response,
            messages=deepcopy(context.messages),
            tools=deepcopy(context.tools),
            llm_response=deepcopy(context.llm_response),
            tool_name=context.tool_name,
            tool_args=deepcopy(context.tool_args),
            tool_result=context.tool_result,
            failed=context.failed,
            metadata=deepcopy(context.metadata),
        )

    def _merge_modify(self, current: HookResult, result: HookResult) -> HookResult:
        merged = dict(current.data)
        merged.update(result.data)
        return HookResult(
            action="modify",
            data=merged,
            message=result.message or current.message,
        )

    def _enforce_permissions(
        self,
        hook: RegisteredHook,
        context: HookContext,
        result: HookResult,
    ) -> HookResult:
        if result.action == "observe":
            return result

        allowed = False
        if result.action == "modify":
            allowed = self._can_modify(context.hook_point, hook.permissions, result.data)
        elif result.action == "skip":
            allowed = context.hook_point == HookPoint.BEFORE_TOOL_CALL and hook.permissions.skip_tool
        elif result.action == "abort":
            allowed = hook.permissions.abort_turn
        elif result.action == "fork":
            allowed = hook.permissions.fork_agent
        elif result.action == "enqueue":
            allowed = hook.permissions.enqueue_task

        if allowed:
            return result

        logger.warning(
            "Hook %s returned unauthorized action %s at %s",
            hook.name,
            result.action,
            context.hook_point.value,
        )
        return HookResult.observe(message=f"unauthorized action ignored: {result.action}")

    def _can_modify(
        self,
        point: HookPoint,
        permissions: HookPermissions,
        data: dict[str, Any],
    ) -> bool:
        keys = set(data)
        if point == HookPoint.MESSAGE_RECEIVED:
            return permissions.modify_message and keys.issubset({"message", "user_message"})
        if point == HookPoint.BEFORE_LLM_CALL:
            return permissions.modify_llm_request and keys.issubset({"messages", "tools"})
        if point == HookPoint.AFTER_LLM_CALL:
            return permissions.modify_llm_response and keys.issubset({"llm_response", "response"})
        if point == HookPoint.BEFORE_TOOL_CALL:
            return permissions.modify_tool_call and keys.issubset({"tool_args", "tool_name"})
        if point == HookPoint.AFTER_TOOL_CALL:
            return permissions.modify_tool_result and keys.issubset({"tool_result", "result"})
        if point == HookPoint.BEFORE_RESPONSE:
            return permissions.modify_response and keys.issubset({"response", "assistant_response"})
        return False
