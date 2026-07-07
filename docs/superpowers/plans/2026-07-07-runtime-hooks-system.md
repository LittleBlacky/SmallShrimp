# Runtime Hooks System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete runtime hook system that supports SmallShrimp lifecycle interception, built-in YAML-controlled hooks, and a later user Python hook layer.

**Architecture:** Implement hooks as an ordered in-process runtime extension layer, separate from EventBus. Phase B adds typed hook primitives, AgentSession integration, built-in hook registry, YAML enablement, and compatibility bridges; Phase C adds controlled user Python hook loading with explicit permissions and isolation.

**Tech Stack:** Python 3.11, dataclasses, pytest, existing SmallShrimp runtime, existing `Config`, existing `AgentSession`, existing fork/subagent runtime.

---

## Scope

This plan implements the B → C route from `docs/superpowers/specs/2026-07-07-runtime-hooks-design.md`.

- Phase B is implemented first and must be usable by internal modules without arbitrary Python hook files.
- Phase C is prepared with clear boundaries and then implemented after Phase B behavior is covered by tests.
- Skill learning is treated as one future built-in hook consumer, not the reason the hook layer exists.
- EventBus remains asynchronous cross-component messaging; hooks are ordered lifecycle interceptors.

## File Structure

- Create `src/SmallShrimp/core/hooks.py`
  - Owns public hook types: `HookPoint`, `HookAction`, `HookPermissions`, `HookContext`, `HookResult`, `RegisteredHook`, `HookManager`.
- Create `src/SmallShrimp/core/hook_builtins.py`
  - Owns built-in hook registry and YAML-driven registration for Phase B.
- Create `src/SmallShrimp/core/hook_user_loader.py`
  - Owns Phase C user Python hook loading, path validation, timeout execution, and permission parsing.
- Modify `src/SmallShrimp/core/runtime/agent.py`
  - Adds `HookManager` to `AgentSession`.
  - Triggers lifecycle hooks around message, context, LLM, tool, response, task, and error points.
  - Bridges existing `set_on_tool_call` and `set_on_thinking`.
- Modify `src/SmallShrimp/core/runtime/fork.py`
  - Emits `fork.created` when a session is forked and hook access is available.
- Modify `src/SmallShrimp/tools/subagent_tool.py`
  - Emits `subagent.started` and `subagent.completed` around direct subagent execution.
- Modify `src/SmallShrimp/utils/config.py`
  - Ensure hook config can be read through the existing config object without special casing elsewhere.
- Create `tests/test_hooks.py`
  - Covers hook manager behavior, permissions, result merging, priority, exception isolation.
- Create `tests/test_runtime_hooks.py`
  - Covers AgentSession lifecycle integration with fake LLM/tool registry.
- Create `tests/test_hook_builtins.py`
  - Covers YAML built-in registration behavior.
- Create `tests/test_hook_user_loader.py`
  - Covers Phase C loader boundaries, timeout, permissions, and error isolation.

---

### Task 1: Core Hook Types and Manager

**Files:**
- Create: `src/SmallShrimp/core/hooks.py`
- Test: `tests/test_hooks.py`

- [ ] **Step 1: Write failing tests for registration, priority, and unsubscribe**

```python
# tests/test_hooks.py
import pytest

from src.SmallShrimp.core.hooks import HookContext, HookManager, HookPoint, HookResult


@pytest.mark.asyncio
async def test_hook_manager_runs_handlers_by_priority():
    manager = HookManager()
    calls: list[str] = []

    async def second(ctx):
        calls.append("second")
        return HookResult.observe()

    async def first(ctx):
        calls.append("first")
        return HookResult.observe()

    manager.register(HookPoint.MESSAGE_RECEIVED, second, priority=200, name="second")
    manager.register(HookPoint.MESSAGE_RECEIVED, first, priority=100, name="first")

    result = await manager.run(
        HookContext(
            hook_point=HookPoint.MESSAGE_RECEIVED,
            session_id="s1",
            agent_id="a1",
            user_message="hello",
        )
    )

    assert result.action == "observe"
    assert calls == ["first", "second"]


@pytest.mark.asyncio
async def test_hook_manager_unsubscribe_removes_handler():
    manager = HookManager()
    calls: list[str] = []

    async def handler(ctx):
        calls.append("called")
        return HookResult.observe()

    unsubscribe = manager.register(HookPoint.MESSAGE_RECEIVED, handler, name="handler")
    unsubscribe()

    await manager.run(
        HookContext(
            hook_point=HookPoint.MESSAGE_RECEIVED,
            session_id="s1",
            agent_id="a1",
            user_message="hello",
        )
    )

    assert calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_hooks.py -v`

Expected: FAIL with `ModuleNotFoundError` or missing hook classes.

- [ ] **Step 3: Implement hook primitives and ordered registration**

```python
# src/SmallShrimp/core/hooks.py
from __future__ import annotations

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
    def observe(cls, message: str = "") -> "HookResult":
        return cls(action="observe", message=message)

    @classmethod
    def modify(cls, data: dict[str, Any], message: str = "") -> "HookResult":
        return cls(action="modify", data=data, message=message)

    @classmethod
    def skip(cls, message: str = "") -> "HookResult":
        return cls(action="skip", message=message)

    @classmethod
    def abort(cls, message: str) -> "HookResult":
        return cls(action="abort", message=message)


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
                result = hook.handler(context)
                if inspect.isawaitable(result):
                    result = await result
                result = self._enforce_permissions(hook, context, result)
            except Exception as exc:
                logger.exception("Hook %s failed at %s", hook.name, context.hook_point.value)
                if hook.critical:
                    raise
                continue

            if result.action == "modify":
                final = self._merge_modify(final, result)
            elif result.action in ("skip", "abort", "fork", "enqueue"):
                return result
            else:
                final = result if final.action == "observe" else final
        return final

    def _merge_modify(self, current: HookResult, result: HookResult) -> HookResult:
        merged = dict(current.data)
        merged.update(result.data)
        return HookResult(action="modify", data=merged, message=result.message or current.message)

    def _enforce_permissions(
        self,
        hook: RegisteredHook,
        context: HookContext,
        result: HookResult,
    ) -> HookResult:
        if result.action == "observe":
            return result
        permissions = hook.permissions
        allowed = False
        if result.action == "modify":
            allowed = self._can_modify(context.hook_point, permissions, result.data)
        elif result.action == "skip":
            allowed = context.hook_point == HookPoint.BEFORE_TOOL_CALL and permissions.skip_tool
        elif result.action == "abort":
            allowed = permissions.abort_turn
        elif result.action == "fork":
            allowed = permissions.fork_agent
        elif result.action == "enqueue":
            allowed = permissions.enqueue_task
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
        if point == HookPoint.MESSAGE_RECEIVED:
            return permissions.modify_message and set(data).issubset({"message", "user_message"})
        if point == HookPoint.BEFORE_LLM_CALL:
            return permissions.modify_llm_request and set(data).issubset({"messages", "tools"})
        if point == HookPoint.AFTER_LLM_CALL:
            return permissions.modify_llm_response and set(data).issubset({"llm_response", "response"})
        if point == HookPoint.BEFORE_TOOL_CALL:
            return permissions.modify_tool_call and set(data).issubset({"tool_args"})
        if point == HookPoint.AFTER_TOOL_CALL:
            return permissions.modify_tool_result and set(data).issubset({"tool_result", "result"})
        if point == HookPoint.BEFORE_RESPONSE:
            return permissions.modify_response and set(data).issubset({"response", "assistant_response"})
        return False
```

- [ ] **Step 4: Run Task 1 tests**

Run: `G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_hooks.py -v`

Expected: PASS for registration tests.

- [ ] **Step 5: Add permission and exception tests**

```python
# tests/test_hooks.py
@pytest.mark.asyncio
async def test_observe_only_hook_cannot_modify_message():
    manager = HookManager()

    async def handler(ctx):
        return HookResult.modify({"message": "changed"})

    manager.register(HookPoint.MESSAGE_RECEIVED, handler, name="observe_only")

    result = await manager.run(
        HookContext(
            hook_point=HookPoint.MESSAGE_RECEIVED,
            session_id="s1",
            agent_id="a1",
            user_message="original",
        )
    )

    assert result.action == "observe"


@pytest.mark.asyncio
async def test_hook_exception_is_isolated_for_non_critical_hooks():
    manager = HookManager()
    calls: list[str] = []

    async def broken(ctx):
        raise RuntimeError("boom")

    async def healthy(ctx):
        calls.append("healthy")
        return HookResult.observe()

    manager.register(HookPoint.AFTER_RESPONSE, broken, priority=100, name="broken")
    manager.register(HookPoint.AFTER_RESPONSE, healthy, priority=200, name="healthy")

    result = await manager.run(
        HookContext(
            hook_point=HookPoint.AFTER_RESPONSE,
            session_id="s1",
            agent_id="a1",
            assistant_response="done",
        )
    )

    assert result.action == "observe"
    assert calls == ["healthy"]
```

- [ ] **Step 6: Run Task 1 full test file**

Run: `G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_hooks.py -v`

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/SmallShrimp/core/hooks.py tests/test_hooks.py
git commit -m "feat: add runtime hook manager"
```

---

### Task 2: AgentSession Lifecycle Integration

**Files:**
- Modify: `src/SmallShrimp/core/runtime/agent.py`
- Test: `tests/test_runtime_hooks.py`

- [ ] **Step 1: Write failing test for message and response hooks**

```python
# tests/test_runtime_hooks.py
import pytest

from src.SmallShrimp.core.hooks import HookPermissions, HookPoint, HookResult
from src.SmallShrimp.core.runtime.agent import AgentSession
from src.SmallShrimp.core.runtime.session_state import SessionState


class FakeAgent:
    def __init__(self):
        self.agent_def = type("AgentDef", (), {"id": "fake", "llm": {}, "metadata": {}})()
        self.context_guard = type("ContextGuard", (), {"check_and_compact": self._compact})()
        self.tool_registry = type("Tools", (), {"get_schemas": lambda self, active_only=True: []})()
        self.history_manager = None
        self.memory_manager = None
        self.pattern_learner = type("PatternLearner", (), {"observe_turn": lambda self, failures, successes: []})()
        self.llm = type("LLM", (), {"chat": self._chat})()

    async def _compact(self, state):
        return state

    async def _chat(self, messages, tools=None, reasoning_content=None):
        return {
            "content": "original response",
            "finish_reason": "stop",
            "tool_calls": None,
            "reasoning_content": None,
            "should_store_reasoning": False,
        }


@pytest.mark.asyncio
async def test_chat_runs_message_and_response_hooks():
    session = AgentSession(
        agent=FakeAgent(),
        state=SessionState(session_id="s1", agent=None, messages=[]),
    )

    async def rewrite_message(ctx):
        return HookResult.modify({"message": "rewritten"})

    async def rewrite_response(ctx):
        return HookResult.modify({"response": "rewritten response"})

    session.hooks.register(
        HookPoint.MESSAGE_RECEIVED,
        rewrite_message,
        name="rewrite_message",
        permissions=HookPermissions(modify_message=True),
    )
    session.hooks.register(
        HookPoint.BEFORE_RESPONSE,
        rewrite_response,
        name="rewrite_response",
        permissions=HookPermissions(modify_response=True),
    )

    result = await session.chat("original")

    assert result == "rewritten response"
    assert session.state.messages[0].content == "rewritten"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_runtime_hooks.py::test_chat_runs_message_and_response_hooks -v`

Expected: FAIL because `AgentSession` has no `hooks` attribute or lifecycle calls.

- [ ] **Step 3: Add `HookManager` to `AgentSession.__post_init__`**

Add this import inside `__post_init__` and initialize after callbacks:

```python
from ..hooks import HookManager

self.hooks = HookManager()
```

- [ ] **Step 4: Integrate message, LLM, and response hooks into `chat()`**

In `chat()`, after `build_turn_context`, add:

```python
from ..hooks import HookContext, HookPoint

agent_id = getattr(self.agent.agent_def, "id", None) or getattr(self.agent.agent_def, "name", "")
message_result = await self.hooks.run(HookContext(
    hook_point=HookPoint.MESSAGE_RECEIVED,
    session_id=self.session_id,
    agent_id=agent_id,
    source=str(self.state.source) if self.state.source else None,
    state=self.state,
    user_message=original_text,
))
if message_result.action == "abort":
    return message_result.message
if message_result.action == "modify":
    original_text = message_result.data.get("message", message_result.data.get("user_message", original_text))
    if self.state.messages:
        self.state.messages[-1].content = original_text
```

Before each LLM call, replace direct `messages` and `schemas` usage with:

```python
llm_request_result = await self.hooks.run(HookContext(
    hook_point=HookPoint.BEFORE_LLM_CALL,
    session_id=self.session_id,
    agent_id=agent_id,
    state=self.state,
    messages=messages,
    tools=schemas,
))
if llm_request_result.action == "abort":
    return llm_request_result.message
if llm_request_result.action == "modify":
    messages = llm_request_result.data.get("messages", messages)
    schemas = llm_request_result.data.get("tools", schemas)
```

After each LLM call, add:

```python
llm_response_result = await self.hooks.run(HookContext(
    hook_point=HookPoint.AFTER_LLM_CALL,
    session_id=self.session_id,
    agent_id=agent_id,
    state=self.state,
    llm_response=response,
))
if llm_response_result.action == "abort":
    return llm_response_result.message
if llm_response_result.action == "modify":
    response = llm_response_result.data.get(
        "llm_response",
        llm_response_result.data.get("response", response),
    )
```

Before creating the final assistant message, add:

```python
response_result = await self.hooks.run(HookContext(
    hook_point=HookPoint.BEFORE_RESPONSE,
    session_id=self.session_id,
    agent_id=agent_id,
    state=self.state,
    user_message=original_text,
    assistant_response=content,
))
if response_result.action == "abort":
    return response_result.message
if response_result.action == "modify":
    content = response_result.data.get(
        "response",
        response_result.data.get("assistant_response", content),
    )
```

After persistence and memory sync, before `return content`, add:

```python
await self.hooks.run(HookContext(
    hook_point=HookPoint.AFTER_RESPONSE,
    session_id=self.session_id,
    agent_id=agent_id,
    state=self.state,
    user_message=original_text,
    assistant_response=content,
))
await self.hooks.run(HookContext(
    hook_point=HookPoint.TASK_COMPLETED,
    session_id=self.session_id,
    agent_id=agent_id,
    state=self.state,
    user_message=original_text,
    assistant_response=content,
))
```

- [ ] **Step 5: Run focused runtime hook test**

Run: `G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_runtime_hooks.py::test_chat_runs_message_and_response_hooks -v`

Expected: PASS.

- [ ] **Step 6: Add error hook test**

```python
# tests/test_runtime_hooks.py
@pytest.mark.asyncio
async def test_chat_runs_error_hook_before_reraising():
    class BrokenAgent(FakeAgent):
        def __init__(self):
            super().__init__()
            self.llm = type("LLM", (), {"chat": self._broken_chat})()

        async def _broken_chat(self, messages, tools=None, reasoning_content=None):
            raise RuntimeError("llm failed")

    session = AgentSession(
        agent=BrokenAgent(),
        state=SessionState(session_id="s1", agent=None, messages=[]),
    )
    seen: list[str] = []

    async def on_error(ctx):
        seen.append(ctx.metadata["error"])
        return HookResult.observe()

    session.hooks.register(HookPoint.ERROR, on_error, name="error_observer")

    with pytest.raises(RuntimeError):
        await session.chat("hello")

    assert seen == ["llm failed"]
```

- [ ] **Step 7: Wrap `chat()` body with error hook**

Refactor `chat()` so the main body is in a `try` block. In `except Exception as exc`, run:

```python
await self.hooks.run(HookContext(
    hook_point=HookPoint.ERROR,
    session_id=self.session_id,
    agent_id=agent_id,
    state=self.state,
    user_message=message,
    failed=True,
    metadata={"error": str(exc), "error_type": type(exc).__name__, "phase": "chat"},
))
await self.hooks.run(HookContext(
    hook_point=HookPoint.TASK_FAILED,
    session_id=self.session_id,
    agent_id=agent_id,
    state=self.state,
    user_message=message,
    failed=True,
    metadata={"error": str(exc), "error_type": type(exc).__name__},
))
raise
```

- [ ] **Step 8: Run Task 2 tests**

Run: `G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_runtime_hooks.py -v`

Expected: PASS.

- [ ] **Step 9: Commit Task 2**

```bash
git add src/SmallShrimp/core/runtime/agent.py tests/test_runtime_hooks.py
git commit -m "feat: integrate hooks into agent runtime"
```

---

### Task 3: Tool Hook Integration and Legacy Callback Bridge

**Files:**
- Modify: `src/SmallShrimp/core/runtime/agent.py`
- Test: `tests/test_runtime_hooks.py`
- Existing tests to run: `tests/test_parallel_tools.py`

- [ ] **Step 1: Write failing test for `tool.before_call` modifying args**

```python
# tests/test_runtime_hooks.py
import json


@pytest.mark.asyncio
async def test_before_tool_hook_can_modify_tool_args():
    executed: list[dict] = []

    class ToolRegistry:
        def get(self, name):
            return None

        async def execute_tool(self, name, **kwargs):
            executed.append(kwargs)
            return "ok"

    agent = FakeAgent()
    agent.tool_registry = ToolRegistry()
    session = AgentSession(agent=agent, state=SessionState(session_id="s1", agent=None, messages=[]))

    async def rewrite_args(ctx):
        return HookResult.modify({"tool_args": {"path": "rewritten.txt"}})

    session.hooks.register(
        HookPoint.BEFORE_TOOL_CALL,
        rewrite_args,
        name="rewrite_tool_args",
        permissions=HookPermissions(modify_tool_call=True),
    )

    await session._execute_tool_calls([
        {
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": json.dumps({"path": "original.txt"}),
            },
        }
    ])

    assert executed == [{"path": "rewritten.txt"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_runtime_hooks.py::test_before_tool_hook_can_modify_tool_args -v`

Expected: FAIL because `_execute_tool_calls()` does not run hook manager.

- [ ] **Step 3: Add before/after tool hooks**

In `_execute_tool_calls()`, after parsing `name` and `args`, run:

```python
from ..hooks import HookContext, HookPoint

agent_id = getattr(self.agent.agent_def, "id", None) or getattr(self.agent.agent_def, "name", "")
before_result = await self.hooks.run(HookContext(
    hook_point=HookPoint.BEFORE_TOOL_CALL,
    session_id=self.session_id,
    agent_id=agent_id,
    state=self.state,
    tool_name=name,
    tool_args=args,
))
if before_result.action == "abort":
    self.state.add_message(ToolMessage(
        content=f"Error: {before_result.message}",
        tool_call_id=tc["id"],
        name=name,
    ))
    continue
if before_result.action == "skip":
    self.state.add_message(ToolMessage(
        content=before_result.message or f"Skipped: {name}",
        tool_call_id=tc["id"],
        name=name,
    ))
    continue
if before_result.action == "modify":
    args = before_result.data.get("tool_args", args)
```

In `_check_guardrail_and_add()`, before budgeting the result, run an async helper because `_check_guardrail_and_add()` must become async:

```python
after_result = await self.hooks.run(HookContext(
    hook_point=HookPoint.AFTER_TOOL_CALL,
    session_id=self.session_id,
    agent_id=agent_id,
    state=self.state,
    tool_name=name,
    tool_args=args,
    tool_result=result,
    failed=failed,
))
if after_result.action == "modify":
    result = after_result.data.get("tool_result", after_result.data.get("result", result))
```

Update all `_check_guardrail_and_add(...)` call sites to `await self._check_guardrail_and_add(...)`.

- [ ] **Step 4: Run focused tool hook test**

Run: `G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_runtime_hooks.py::test_before_tool_hook_can_modify_tool_args -v`

Expected: PASS.

- [ ] **Step 5: Add legacy callback bridge test**

```python
# tests/test_runtime_hooks.py
@pytest.mark.asyncio
async def test_set_on_tool_call_still_receives_after_tool_event():
    seen: list[tuple[str, bool]] = []

    class ToolRegistry:
        def get(self, name):
            return None

        async def execute_tool(self, name, **kwargs):
            return "ok"

    agent = FakeAgent()
    agent.tool_registry = ToolRegistry()
    session = AgentSession(agent=agent, state=SessionState(session_id="s1", agent=None, messages=[]))
    session.set_on_tool_call(lambda name, args, result, failed: seen.append((name, failed)))

    await session._execute_tool_calls([
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "read_file", "arguments": "{}"},
        }
    ])

    assert seen == [("read_file", False)]
```

- [ ] **Step 6: Keep `set_on_tool_call` as compatibility surface**

Do not remove `_on_tool_call`. Leave existing direct callback in `_check_guardrail_and_add()` so CLI behavior remains unchanged. The compatibility requirement is behavioral, not a forced internal rewrite.

- [ ] **Step 7: Add thinking callback test**

```python
# tests/test_runtime_hooks.py
@pytest.mark.asyncio
async def test_set_on_thinking_still_receives_reasoning_content():
    class ReasoningAgent(FakeAgent):
        async def _chat(self, messages, tools=None, reasoning_content=None):
            return {
                "content": "done",
                "finish_reason": "stop",
                "tool_calls": None,
                "reasoning_content": "thinking",
                "should_store_reasoning": False,
            }

    session = AgentSession(
        agent=ReasoningAgent(),
        state=SessionState(session_id="s1", agent=None, messages=[]),
    )
    seen: list[str] = []
    session.set_on_thinking(seen.append)

    await session.chat("hello")

    assert seen == ["thinking"]
```

- [ ] **Step 8: Run runtime and parallel tool tests**

Run: `G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_runtime_hooks.py tests/test_parallel_tools.py -v`

Expected: PASS.

- [ ] **Step 9: Commit Task 3**

```bash
git add src/SmallShrimp/core/runtime/agent.py tests/test_runtime_hooks.py tests/test_parallel_tools.py
git commit -m "feat: add tool lifecycle hooks"
```

---

### Task 4: Built-In YAML Hook Registry

**Files:**
- Create: `src/SmallShrimp/core/hook_builtins.py`
- Modify: `src/SmallShrimp/core/runtime/agent.py`
- Test: `tests/test_hook_builtins.py`

- [ ] **Step 1: Write failing tests for YAML built-in registration**

```python
# tests/test_hook_builtins.py
import pytest

from src.SmallShrimp.core.hook_builtins import register_builtin_hooks
from src.SmallShrimp.core.hooks import HookContext, HookPoint
from src.SmallShrimp.core.runtime.agent import AgentSession
from src.SmallShrimp.core.runtime.session_state import SessionState
from tests.test_runtime_hooks import FakeAgent


@pytest.mark.asyncio
async def test_register_builtin_audit_log_from_config(tmp_path):
    log_path = tmp_path / "hooks.log"
    agent = FakeAgent()
    agent.config = type("Config", (), {
        "data": {
            "hooks": {
                "enabled": True,
                "builtin": {
                    "audit_log": {
                        "enabled": True,
                        "point": "tool.after_call",
                        "path": str(log_path),
                    }
                },
            }
        }
    })()
    session = AgentSession(agent=agent, state=SessionState(session_id="s1", agent=None, messages=[]))

    register_builtin_hooks(session.hooks, agent.config.data.get("hooks", {}))

    await session.hooks.run(HookContext(
        hook_point=HookPoint.AFTER_TOOL_CALL,
        session_id="s1",
        agent_id="fake",
        tool_name="read_file",
        tool_args={"path": "a.txt"},
        tool_result="ok",
    ))

    assert "read_file" in log_path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_hook_builtins.py -v`

Expected: FAIL because `hook_builtins.py` does not exist.

- [ ] **Step 3: Implement built-in registry with audit hook and skill-learning stub**

```python
# src/SmallShrimp/core/hook_builtins.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .hooks import HookManager, HookPermissions, HookPoint, HookResult


BuiltinFactory = Callable[[dict[str, Any]], tuple[HookPoint, Callable, HookPermissions]]


def _audit_log_factory(config: dict[str, Any]):
    point = HookPoint(config.get("point", HookPoint.AFTER_TOOL_CALL.value))
    path = Path(config.get("path", "workspace/.cache/hooks/audit.log"))

    async def audit_log(ctx):
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "hook_point": ctx.hook_point.value,
            "session_id": ctx.session_id,
            "agent_id": ctx.agent_id,
            "tool_name": ctx.tool_name,
            "failed": ctx.failed,
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return HookResult.observe()

    return point, audit_log, HookPermissions(observe=True, write_files=True)


def _skill_learning_factory(config: dict[str, Any]):
    point = HookPoint(config.get("point", HookPoint.TASK_COMPLETED.value))

    async def skill_learning_stub(ctx):
        ctx.metadata.setdefault("skill_learning_checked", True)
        return HookResult.observe("skill learning stub evaluated")

    return point, skill_learning_stub, HookPermissions(observe=True)


BUILTIN_HOOKS: dict[str, BuiltinFactory] = {
    "audit_log": _audit_log_factory,
    "skill_learning": _skill_learning_factory,
}


def register_builtin_hooks(manager: HookManager, hooks_config: dict[str, Any] | None) -> list[str]:
    config = hooks_config or {}
    if not config.get("enabled", False):
        return []
    registered: list[str] = []
    for name, item in (config.get("builtin") or {}).items():
        if not isinstance(item, dict) or not item.get("enabled", False):
            continue
        factory = BUILTIN_HOOKS.get(name)
        if factory is None:
            continue
        point, handler, permissions = factory(item)
        manager.register(
            point,
            handler,
            name=f"builtin.{name}",
            priority=int(item.get("priority", 500)),
            permissions=permissions,
            source="builtin",
        )
        registered.append(name)
    return registered
```

- [ ] **Step 4: Run built-in hook tests**

Run: `G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_hook_builtins.py -v`

Expected: PASS.

- [ ] **Step 5: Wire built-in hooks during session initialization**

In `AgentSession.__post_init__`, after `self.hooks = HookManager()`, add:

```python
config_data = getattr(getattr(self.agent, "config", None), "data", {})
hooks_config = config_data.get("hooks", {}) if isinstance(config_data, dict) else {}
if hooks_config:
    from ..hook_builtins import register_builtin_hooks
    register_builtin_hooks(self.hooks, hooks_config)
```

- [ ] **Step 6: Add test that `AgentSession` auto-registers built-ins from config**

```python
# tests/test_hook_builtins.py
def test_agent_session_registers_builtin_hooks_from_agent_config(tmp_path):
    log_path = tmp_path / "hooks.log"
    agent = FakeAgent()
    agent.config = type("Config", (), {
        "data": {
            "hooks": {
                "enabled": True,
                "builtin": {
                    "audit_log": {
                        "enabled": True,
                        "point": "tool.after_call",
                        "path": str(log_path),
                    }
                },
            }
        }
    })()

    session = AgentSession(agent=agent, state=SessionState(session_id="s1", agent=None, messages=[]))

    assert [hook.name for hook in session.hooks.list_hooks(HookPoint.AFTER_TOOL_CALL)] == ["builtin.audit_log"]
```

- [ ] **Step 7: Run Task 4 tests**

Run: `G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_hook_builtins.py tests/test_runtime_hooks.py -v`

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

```bash
git add src/SmallShrimp/core/hook_builtins.py src/SmallShrimp/core/runtime/agent.py tests/test_hook_builtins.py
git commit -m "feat: load builtin hooks from config"
```

---

### Task 5: Fork and Subagent Hook Points

**Files:**
- Modify: `src/SmallShrimp/core/runtime/fork.py`
- Modify: `src/SmallShrimp/tools/subagent_tool.py`
- Test: `tests/test_fork_session.py`
- Test: `tests/test_dispatch.py`

- [ ] **Step 1: Write failing fork hook test**

```python
# tests/test_fork_session.py
from src.SmallShrimp.core.hooks import HookPoint, HookResult


def test_fork_session_emits_fork_created_hook_when_available():
    session = _make_session_with_messages(["one", "two"])
    seen: list[str] = []

    async def on_fork(ctx):
        seen.append(ctx.parent_session_id)
        return HookResult.observe()

    session.hooks.register(HookPoint.FORK_CREATED, on_fork, name="fork_observer")

    forked = fork_session(session, ForkOptions(task="child task"))

    assert forked.parent_session_id == session.session_id
    assert seen == [session.session_id]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_fork_session.py::test_fork_session_emits_fork_created_hook_when_available -v`

Expected: FAIL because `fork_session()` is sync and cannot await hook handlers.

- [ ] **Step 3: Choose non-blocking sync-safe fork hook behavior**

Implement fork hook emission as best-effort:

```python
# src/SmallShrimp/core/runtime/fork.py
def _emit_fork_hook(parent_session, forked: ForkedSession) -> None:
    hooks = getattr(parent_session, "hooks", None)
    if hooks is None:
        return
    import asyncio
    from ..hooks import HookContext, HookPoint

    agent_def = parent_session.agent.agent_def
    agent_id = getattr(agent_def, "id", None) or getattr(agent_def, "name", "")
    context = HookContext(
        hook_point=HookPoint.FORK_CREATED,
        session_id=forked.session_id,
        parent_session_id=forked.parent_session_id,
        agent_id=agent_id,
        state=parent_session.state,
        metadata={"task": forked.task},
    )
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(hooks.run(context))
    else:
        loop.create_task(hooks.run(context))
```

Call `_emit_fork_hook(parent_session, forked)` after `_persist_fork(...)`.

Update the test to use `pytest.mark.asyncio` and `await asyncio.sleep(0)` if it runs inside an event loop.

- [ ] **Step 4: Run fork tests**

Run: `G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_fork_session.py -v`

Expected: PASS.

- [ ] **Step 5: Write subagent hook test**

```python
# tests/test_dispatch.py
@pytest.mark.asyncio
async def test_subagent_dispatch_emits_started_and_completed_hooks(context):
    tool = create_subagent_dispatch_tool("main", context)
    parent_session = context.agent_loader.load("main").new_session()
    seen: list[str] = []

    async def started(ctx):
        seen.append("started")
        return HookResult.observe()

    async def completed(ctx):
        seen.append("completed")
        return HookResult.observe()

    parent_session.hooks.register(HookPoint.SUBAGENT_STARTED, started, name="started")
    parent_session.hooks.register(HookPoint.SUBAGENT_COMPLETED, completed, name="completed")

    with patch("src.SmallShrimp.core.runtime.agent.AgentSession.run_once", new_callable=AsyncMock) as run_once:
        run_once.return_value = AgentResult(text="done", input_tokens=1, output_tokens=1, session_id="child")
        await tool.func(agent_id="helper", task="do work", session=parent_session)

    assert seen == ["started", "completed"]
```

- [ ] **Step 6: Add subagent hook emission**

In `src/SmallShrimp/tools/subagent_tool.py`, before `run_once`, add:

```python
from ..core.hooks import HookContext, HookPoint

await session.hooks.run(HookContext(
    hook_point=HookPoint.SUBAGENT_STARTED,
    session_id=session.session_id,
    agent_id=current_agent_id,
    state=session.state,
    metadata={"subagent_id": agent_id, "task": task, "agent_type": agent_type},
))
```

After `run_once`, add:

```python
await session.hooks.run(HookContext(
    hook_point=HookPoint.SUBAGENT_COMPLETED,
    session_id=session.session_id,
    agent_id=current_agent_id,
    state=session.state,
    metadata={
        "subagent_id": agent_id,
        "task": task,
        "agent_type": agent_type,
        "subagent_session_id": result.session_id,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    },
))
```

- [ ] **Step 7: Run fork and dispatch tests**

Run: `G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_fork_session.py tests/test_dispatch.py -v`

Expected: PASS.

- [ ] **Step 8: Commit Task 5**

```bash
git add src/SmallShrimp/core/runtime/fork.py src/SmallShrimp/tools/subagent_tool.py tests/test_fork_session.py tests/test_dispatch.py
git commit -m "feat: emit fork and subagent hooks"
```

---

### Task 6: Phase C User Python Hook Loader

**Files:**
- Create: `src/SmallShrimp/core/hook_user_loader.py`
- Modify: `src/SmallShrimp/core/hook_builtins.py`
- Test: `tests/test_hook_user_loader.py`

- [ ] **Step 1: Write failing tests for allowed path validation**

```python
# tests/test_hook_user_loader.py
from pathlib import Path

import pytest

from src.SmallShrimp.core.hook_user_loader import UserHookConfig, load_user_hooks
from src.SmallShrimp.core.hooks import HookManager, HookPoint


def test_user_hook_loader_rejects_paths_outside_workspace(tmp_path):
    manager = HookManager()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("async def handle(ctx): return None", encoding="utf-8")

    configs = [
        UserHookConfig(
            name="outside",
            enabled=True,
            module=str(outside),
            handler="handle",
            point=HookPoint.BEFORE_RESPONSE.value,
        )
    ]

    loaded = load_user_hooks(manager, configs, workspace)

    assert loaded == []
    assert manager.list_hooks(HookPoint.BEFORE_RESPONSE) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_hook_user_loader.py::test_user_hook_loader_rejects_paths_outside_workspace -v`

Expected: FAIL because loader does not exist.

- [ ] **Step 3: Implement loader dataclass and path boundary**

```python
# src/SmallShrimp/core/hook_user_loader.py
from __future__ import annotations

import asyncio
import importlib.util
import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .hooks import HookManager, HookPermissions, HookPoint, HookResult

logger = logging.getLogger(__name__)


@dataclass
class UserHookConfig:
    name: str
    enabled: bool
    module: str
    handler: str
    point: str
    timeout_ms: int = 1000
    priority: int = 500
    permissions: dict[str, Any] = field(default_factory=dict)


def load_user_hooks(
    manager: HookManager,
    configs: list[UserHookConfig],
    workspace: str | Path,
) -> list[str]:
    workspace_path = Path(workspace).resolve()
    allowed_root = (workspace_path / "hooks").resolve()
    loaded: list[str] = []

    for config in configs:
        if not config.enabled:
            continue
        module_path = Path(config.module)
        if not module_path.is_absolute():
            module_path = workspace_path / module_path
        module_path = module_path.resolve()
        if not _is_relative_to(module_path, allowed_root):
            logger.warning("Skipping user hook outside workspace hooks directory: %s", module_path)
            continue
        if not module_path.exists() or module_path.suffix != ".py":
            logger.warning("Skipping missing or non-Python user hook: %s", module_path)
            continue

        handler = _load_handler(module_path, config.handler)
        if handler is None:
            continue
        permissions = HookPermissions(**{k: v for k, v in config.permissions.items() if hasattr(HookPermissions, k)})
        wrapped = _with_timeout(handler, config.timeout_ms)
        manager.register(
            HookPoint(config.point),
            wrapped,
            name=f"user.{config.name}",
            priority=config.priority,
            permissions=permissions,
            source="user",
        )
        loaded.append(config.name)
    return loaded


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _load_handler(module_path: Path, handler_name: str):
    spec = importlib.util.spec_from_file_location(f"smallshrimp_user_hook_{module_path.stem}", module_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    handler = getattr(module, handler_name, None)
    if handler is None or not callable(handler):
        return None
    return handler


def _with_timeout(handler, timeout_ms: int):
    async def wrapped(ctx):
        async def run_handler():
            result = handler(ctx)
            if inspect.isawaitable(result):
                return await result
            return result

        try:
            result = await asyncio.wait_for(run_handler(), timeout=max(timeout_ms, 1) / 1000)
        except asyncio.TimeoutError:
            logger.warning("User hook timed out: %s", getattr(handler, "__name__", "hook"))
            return HookResult.observe("user hook timed out")
        if isinstance(result, HookResult):
            return result
        return HookResult.observe()

    return wrapped
```

- [ ] **Step 4: Run path validation test**

Run: `G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_hook_user_loader.py::test_user_hook_loader_rejects_paths_outside_workspace -v`

Expected: PASS.

- [ ] **Step 5: Add user hook loading and timeout tests**

```python
# tests/test_hook_user_loader.py
import asyncio

from src.SmallShrimp.core.hooks import HookContext


@pytest.mark.asyncio
async def test_user_hook_loader_registers_enabled_workspace_hook(tmp_path):
    workspace = tmp_path / "workspace"
    hooks_dir = workspace / "hooks"
    hooks_dir.mkdir(parents=True)
    hook_file = hooks_dir / "rewrite.py"
    hook_file.write_text(
        "from src.SmallShrimp.core.hooks import HookResult\n"
        "async def handle(ctx):\n"
        "    return HookResult.modify({'response': 'changed'})\n",
        encoding="utf-8",
    )
    manager = HookManager()

    loaded = load_user_hooks(manager, [
        UserHookConfig(
            name="rewrite",
            enabled=True,
            module="hooks/rewrite.py",
            handler="handle",
            point=HookPoint.BEFORE_RESPONSE.value,
            permissions={"modify_response": True},
        )
    ], workspace)

    result = await manager.run(HookContext(
        hook_point=HookPoint.BEFORE_RESPONSE,
        session_id="s1",
        agent_id="a1",
        assistant_response="original",
    ))

    assert loaded == ["rewrite"]
    assert result.action == "modify"
    assert result.data["response"] == "changed"


@pytest.mark.asyncio
async def test_user_hook_timeout_is_isolated(tmp_path):
    workspace = tmp_path / "workspace"
    hooks_dir = workspace / "hooks"
    hooks_dir.mkdir(parents=True)
    hook_file = hooks_dir / "slow.py"
    hook_file.write_text(
        "import asyncio\n"
        "async def handle(ctx):\n"
        "    await asyncio.sleep(1)\n",
        encoding="utf-8",
    )
    manager = HookManager()
    load_user_hooks(manager, [
        UserHookConfig(
            name="slow",
            enabled=True,
            module="hooks/slow.py",
            handler="handle",
            point=HookPoint.BEFORE_RESPONSE.value,
            timeout_ms=1,
        )
    ], workspace)

    result = await manager.run(HookContext(
        hook_point=HookPoint.BEFORE_RESPONSE,
        session_id="s1",
        agent_id="a1",
        assistant_response="original",
    ))

    assert result.action == "observe"
```

- [ ] **Step 6: Run Phase C loader tests**

Run: `G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_hook_user_loader.py -v`

Expected: PASS.

- [ ] **Step 7: Commit Task 6**

```bash
git add src/SmallShrimp/core/hook_user_loader.py tests/test_hook_user_loader.py
git commit -m "feat: add controlled user hook loader"
```

---

### Task 7: Config Integration for User Hooks

**Files:**
- Modify: `src/SmallShrimp/core/runtime/agent.py`
- Modify: `src/SmallShrimp/core/hook_user_loader.py`
- Test: `tests/test_hook_user_loader.py`

- [ ] **Step 1: Write config parsing test**

```python
# tests/test_hook_user_loader.py
from src.SmallShrimp.core.hook_user_loader import configs_from_mapping


def test_configs_from_mapping_parses_user_hook_list():
    raw = {
        "user": {
            "local_quality_gate": {
                "enabled": True,
                "module": "hooks/local_quality_gate.py",
                "handler": "handle",
                "point": "response.before",
                "timeout_ms": 1000,
                "permissions": {"observe": True, "modify_response": True},
            }
        }
    }

    configs = configs_from_mapping(raw)

    assert len(configs) == 1
    assert configs[0].name == "local_quality_gate"
    assert configs[0].point == "response.before"
    assert configs[0].permissions["modify_response"] is True
```

- [ ] **Step 2: Implement config parser**

```python
# src/SmallShrimp/core/hook_user_loader.py
def configs_from_mapping(hooks_config: dict[str, Any] | None) -> list[UserHookConfig]:
    raw_user = (hooks_config or {}).get("user") or {}
    configs: list[UserHookConfig] = []
    for name, item in raw_user.items():
        if not isinstance(item, dict):
            continue
        configs.append(UserHookConfig(
            name=name,
            enabled=bool(item.get("enabled", False)),
            module=str(item.get("module", "")),
            handler=str(item.get("handler", "handle")),
            point=str(item.get("point", HookPoint.AFTER_RESPONSE.value)),
            timeout_ms=int(item.get("timeout_ms", 1000)),
            priority=int(item.get("priority", 500)),
            permissions=dict(item.get("permissions") or {}),
        ))
    return configs
```

- [ ] **Step 3: Wire user hook loading behind explicit config**

In `AgentSession.__post_init__`, after built-in hook registration, add:

```python
if hooks_config.get("user"):
    from pathlib import Path
    from ..hook_user_loader import configs_from_mapping, load_user_hooks
    workspace = config_data.get("workspace", "workspace") if isinstance(config_data, dict) else "workspace"
    load_user_hooks(self.hooks, configs_from_mapping(hooks_config), Path(workspace))
```

- [ ] **Step 4: Run config and loader tests**

Run: `G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_hook_user_loader.py tests/test_hook_builtins.py -v`

Expected: PASS.

- [ ] **Step 5: Commit Task 7**

```bash
git add src/SmallShrimp/core/runtime/agent.py src/SmallShrimp/core/hook_user_loader.py tests/test_hook_user_loader.py
git commit -m "feat: load user hooks from config"
```

---

### Task 8: Documentation and Example Configuration

**Files:**
- Modify: `docs/hooks-system-design.md`
- Modify: `docs/superpowers/specs/2026-07-07-runtime-hooks-design.md`
- Create: `docs/runtime-hooks.md`
- Do not modify: `workspace/config.user.yaml` unless user explicitly asks to enable hooks in their local runtime.

- [ ] **Step 1: Create user-facing hook docs**

Write `docs/runtime-hooks.md` with:

```markdown
# Runtime Hooks

SmallShrimp hooks are ordered runtime lifecycle interceptors. They are separate from EventBus: hooks can observe, modify, skip, abort, fork, or enqueue work during an agent turn; EventBus is for asynchronous cross-component messaging.

## Phase B: Built-In Hooks

Built-in hooks are registered by SmallShrimp code and enabled through YAML.

```yaml
hooks:
  enabled: true
  builtin:
    audit_log:
      enabled: true
      point: tool.after_call
      path: workspace/.cache/hooks/audit.log
    skill_learning:
      enabled: false
      point: task.completed
      mode: auto_draft
```

Unknown built-in hook names are ignored. YAML can enable and configure built-ins, but cannot import arbitrary Python code in Phase B.

## Phase C: User Python Hooks

User hooks must live under `workspace/hooks/`, be explicitly enabled, declare a handler, and receive explicit permissions.

```yaml
hooks:
  enabled: true
  user:
    local_quality_gate:
      enabled: true
      module: hooks/local_quality_gate.py
      handler: handle
      point: response.before
      timeout_ms: 1000
      permissions:
        observe: true
        modify_response: true
```

Example handler:

```python
from src.SmallShrimp.core.hooks import HookResult

async def handle(ctx):
    response = ctx.assistant_response or ""
    return HookResult.modify({"response": response.strip()})
```

## Hook Points

- `session.start`
- `session.end`
- `message.received`
- `context.built`
- `llm.before_call`
- `llm.after_call`
- `tool.before_call`
- `tool.after_call`
- `response.before`
- `response.after`
- `task.completed`
- `task.failed`
- `fork.created`
- `subagent.started`
- `subagent.completed`
- `error`
```

- [ ] **Step 2: Update old hook design doc to point to current spec**

At the top of `docs/hooks-system-design.md`, add:

```markdown
> Current implementation direction lives in `docs/superpowers/specs/2026-07-07-runtime-hooks-design.md` and `docs/runtime-hooks.md`. This document is retained as earlier background.
```

- [ ] **Step 3: Run documentation quality check**

Run:

```bash
G:\Anaconda\envs\smallshrimp\python.exe -c "from pathlib import Path; terms=['TO'+'DO','TB'+'D','implement '+'later','fill in '+'details']; files=[Path('docs/runtime-hooks.md'),Path('docs/superpowers/plans/2026-07-07-runtime-hooks-system.md')]; hits=[f'{p}:{i}: {line}' for p in files if p.exists() for i,line in enumerate(p.read_text(encoding='utf-8').splitlines(),1) if any(t in line for t in terms)]; print('\n'.join(hits)); raise SystemExit(1 if hits else 0)"
```

Expected: no output.

- [ ] **Step 4: Commit Task 8**

```bash
git add docs/runtime-hooks.md docs/hooks-system-design.md docs/superpowers/specs/2026-07-07-runtime-hooks-design.md
git commit -m "docs: document runtime hooks"
```

---

### Task 9: Full Verification

**Files:**
- No new files.
- Run verification commands.

- [ ] **Step 1: Run focused hook suite**

Run:

```bash
G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_hooks.py tests/test_runtime_hooks.py tests/test_hook_builtins.py tests/test_hook_user_loader.py -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run affected existing tests**

Run:

```bash
G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_fork_session.py tests/test_dispatch.py tests/test_parallel_tools.py tests/test_commands.py -v
```

Expected: all tests PASS.

- [ ] **Step 3: Compile source**

Run:

```bash
G:\Anaconda\envs\smallshrimp\python.exe -m compileall -q src\SmallShrimp
```

Expected: exit code 0.

- [ ] **Step 4: Run full test suite if time allows**

Run:

```bash
G:\Anaconda\envs\smallshrimp\python.exe -m pytest
```

Expected: all tests PASS or unrelated pre-existing failures documented with exact failing test names.

- [ ] **Step 5: Commit verification updates**

If Task 9 required code or doc fixes:

```bash
git add src tests docs
git commit -m "test: verify runtime hooks"
```

If no files changed, do not create an empty commit.

---

## Self-Review Against Spec

- Hook lifecycle coverage: Tasks 2, 3, and 5 cover message, context-adjacent LLM request, LLM response, tool call, response, task completion/failure, error, fork, and subagent points.
- Built-in YAML hooks: Task 4 implements Phase B with code-owned factories and YAML enablement.
- User Python hooks: Tasks 6 and 7 implement Phase C with explicit workspace boundary, timeout, permissions, and error isolation.
- Permission checks: Task 1 enforces action permissions centrally in `HookManager`.
- Existing callbacks: Task 3 keeps `set_on_tool_call`, `set_on_thinking`, and `set_confirm_fn` behavior intact.
- Skill learning boundary: Task 4 adds only a stub; full automatic skill learning remains a later built-in hook consumer.
- EventBus boundary: This plan does not replace EventBus or use it for blocking lifecycle interception.
