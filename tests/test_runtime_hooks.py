from __future__ import annotations

import pytest

from src.SmallShrimp.core.hooks import HookPermissions, HookPoint, HookResult
from src.SmallShrimp.core.runtime.agent import AgentSession
from src.SmallShrimp.core.runtime.message import AssistantMessage, HumanMessage, ToolMessage
from src.SmallShrimp.core.runtime.session_state import SessionState


class FakeAgentDef:
    id = "fake-agent"
    name = "fake"
    description = "Fake test agent"
    guidelines: list[str] = []
    instructions: list[str] = []
    llm = {"context_window": 10000}
    metadata: dict = {}


class FakeConfig:
    data = {"workspace": "workspace"}

    def get(self, key, default=None):
        if key == "max_iterations":
            return 3
        return default


class FakeContextGuard:
    async def check_and_compact(self, state):
        return state


class FakePatternLearner:
    def observe_turn(self, failures, successes):
        return []


class FakeToolRegistry:
    def __init__(self, result="tool result", tools=None):
        self.result = result
        self.tools = tools or {}
        self.calls: list[tuple[str, dict]] = []

    def get_schemas(self, active_only=True):
        return []

    def get(self, name):
        return self.tools.get(name)

    async def execute_tool(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return self.result


class FakeTrustManager:
    def is_trusted(self, cwd):
        return True

    def scan_dangerous(self, cwd):
        return []


class FakeLLM:
    thinking_strategy = None

    def __init__(self, response=None, exc=None):
        self.responses = list(response) if isinstance(response, list) else None
        self.response = response or {
            "content": "original response",
            "finish_reason": "stop",
            "tool_calls": None,
            "reasoning_content": None,
            "should_store_reasoning": False,
        }
        self.exc = exc
        self.calls: list[dict] = []

    async def chat(self, messages, tools=None, reasoning_content=None):
        self.calls.append({"messages": messages, "tools": tools})
        if self.exc is not None:
            raise self.exc
        if self.responses is not None:
            return dict(self.responses.pop(0))
        return dict(self.response)


class FakeAgent:
    def __init__(self, llm=None, tool_registry=None):
        self.agent_def = FakeAgentDef()
        self.config = FakeConfig()
        self.context_guard = FakeContextGuard()
        self.tool_registry = tool_registry or FakeToolRegistry()
        self.history_manager = None
        self.memory_manager = None
        self.pattern_learner = FakePatternLearner()
        self.trust_manager = FakeTrustManager()
        self.llm = llm or FakeLLM()
        self._mcp_registered = True


def make_session(agent=None):
    fake_agent = agent or FakeAgent()
    state = SessionState(session_id="s1", agent=fake_agent, messages=[])
    return AgentSession(agent=fake_agent, state=state)


@pytest.mark.asyncio
async def test_chat_runs_message_and_response_hooks():
    session = make_session()

    async def rewrite_message(ctx):
        return HookResult.modify({"message": "rewritten"})

    async def rewrite_response(ctx):
        return HookResult.modify({"response": f"{ctx.assistant_response} + hook"})

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

    assert result == "original response + hook"
    assert isinstance(session.state.messages[0], HumanMessage)
    assert session.state.messages[0].content == "rewritten"


@pytest.mark.asyncio
async def test_chat_runs_error_hook_before_reraising():
    error = RuntimeError("llm exploded")
    session = make_session(FakeAgent(llm=FakeLLM(exc=error)))
    observed: list[object] = []

    async def observe_error(ctx):
        observed.append(ctx.metadata["error"])
        return HookResult.observe()

    session.hooks.register(HookPoint.ERROR, observe_error, name="observe_error")

    with pytest.raises(RuntimeError, match="llm exploded") as excinfo:
        await session.chat("hello")

    assert excinfo.value is error
    assert len(observed) == 1
    assert isinstance(observed[0], RuntimeError)
    assert str(observed[0]) == "llm exploded"


@pytest.mark.asyncio
async def test_chat_error_hook_failure_does_not_mask_original_exception():
    error = RuntimeError("llm exploded")
    session = make_session(FakeAgent(llm=FakeLLM(exc=error)))
    task_failed_errors: list[str] = []

    async def broken_error_hook(ctx):
        raise RuntimeError("hook exploded")

    async def observe_task_failed(ctx):
        task_failed_errors.append(str(ctx.metadata["error"]))
        return HookResult.observe()

    session.hooks.register(
        HookPoint.ERROR,
        broken_error_hook,
        name="broken_error_hook",
        critical=True,
    )
    session.hooks.register(
        HookPoint.TASK_FAILED,
        observe_task_failed,
        name="observe_task_failed",
    )

    with pytest.raises(RuntimeError, match="llm exploded") as excinfo:
        await session.chat("hello")

    assert excinfo.value is error
    assert task_failed_errors == ["llm exploded"]


@pytest.mark.asyncio
async def test_chat_runs_llm_after_call_hook_can_modify_response():
    session = make_session()

    async def rewrite_llm_response(ctx):
        response = dict(ctx.llm_response)
        response["content"] = "modified by after hook"
        return HookResult.modify({"llm_response": response})

    session.hooks.register(
        HookPoint.AFTER_LLM_CALL,
        rewrite_llm_response,
        name="rewrite_llm_response",
        permissions=HookPermissions(modify_llm_response=True),
    )

    result = await session.chat("hello")

    assert result == "modified by after hook"


@pytest.mark.asyncio
async def test_chat_runs_llm_after_call_hook_for_empty_response_nudge():
    llm = FakeLLM(response=[
        {
            "content": "",
            "finish_reason": "stop",
            "tool_calls": None,
            "reasoning_content": None,
            "should_store_reasoning": False,
        },
        {
            "content": "nudge response",
            "finish_reason": "stop",
            "tool_calls": None,
            "reasoning_content": None,
            "should_store_reasoning": False,
        },
    ])
    session = make_session(FakeAgent(llm=llm))
    session._had_tool_calls_this_turn = lambda: True
    seen_contents: list[str] = []

    async def observe_llm_response(ctx):
        seen_contents.append(ctx.llm_response.get("content", ""))
        return HookResult.observe()

    session.hooks.register(
        HookPoint.AFTER_LLM_CALL,
        observe_llm_response,
        name="observe_llm_response",
    )

    result = await session.chat("hello")

    assert result == "nudge response"
    assert seen_contents == ["", "nudge response"]
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_response_after_and_task_completed_abort_do_not_change_response():
    session = make_session()

    async def abort_response_after(ctx):
        return HookResult.abort("after abort")

    async def abort_task_completed(ctx):
        return HookResult.abort("completed abort")

    session.hooks.register(
        HookPoint.AFTER_RESPONSE,
        abort_response_after,
        name="abort_response_after",
        permissions=HookPermissions(abort_turn=True),
    )
    session.hooks.register(
        HookPoint.TASK_COMPLETED,
        abort_task_completed,
        name="abort_task_completed",
        permissions=HookPermissions(abort_turn=True),
    )

    result = await session.chat("hello")

    assert result == "original response"
    assert session.state.messages[-1].content == "original response"


@pytest.mark.asyncio
async def test_max_iteration_fallback_runs_response_hooks_and_task_failed():
    session = make_session(FakeAgent(llm=FakeLLM(response={
        "content": "",
        "finish_reason": "tool_calls",
        "tool_calls": [
            {
                "id": "call_1",
                "function": {"name": "missing_tool", "arguments": "{}"},
            }
        ],
        "reasoning_content": None,
        "should_store_reasoning": False,
    })))
    async def execute_tool_calls_noop(tool_calls):
        return None

    session._execute_tool_calls = execute_tool_calls_noop
    before_seen: list[str] = []
    after_seen: list[str] = []
    failed_reasons: list[str] = []

    async def before_response(ctx):
        before_seen.append(ctx.assistant_response)
        return HookResult.modify({"response": "modified fallback"})

    async def after_response(ctx):
        after_seen.append(ctx.assistant_response)
        return HookResult.observe()

    async def task_failed(ctx):
        failed_reasons.append(ctx.metadata["reason"])
        return HookResult.observe()

    session.hooks.register(
        HookPoint.BEFORE_RESPONSE,
        before_response,
        name="before_response",
        permissions=HookPermissions(modify_response=True),
    )
    session.hooks.register(HookPoint.AFTER_RESPONSE, after_response, name="after_response")
    session.hooks.register(HookPoint.TASK_FAILED, task_failed, name="task_failed")

    result = await session.chat("hello")

    assert result == "modified fallback"
    assert before_seen == ["[达到最大工具调用轮次限制，请简化请求后重试。]"]
    assert after_seen == ["modified fallback"]
    assert failed_reasons == ["max_iterations"]
    assert isinstance(session.state.messages[-1], AssistantMessage)
    assert session.state.messages[-1].content == "modified fallback"


@pytest.mark.asyncio
async def test_response_before_sees_effective_nudge_llm_response():
    llm = FakeLLM(response=[
        {
            "content": "",
            "finish_reason": "stop",
            "tool_calls": None,
            "reasoning_content": None,
            "should_store_reasoning": False,
        },
        {
            "content": "nudge response",
            "finish_reason": "stop",
            "tool_calls": None,
            "reasoning_content": None,
            "should_store_reasoning": False,
        },
    ])
    session = make_session(FakeAgent(llm=llm))
    session._had_tool_calls_this_turn = lambda: True
    before_response_contents: list[str] = []

    async def observe_before_response(ctx):
        before_response_contents.append(ctx.llm_response.get("content", ""))
        return HookResult.observe()

    session.hooks.register(
        HookPoint.BEFORE_RESPONSE,
        observe_before_response,
        name="observe_before_response",
    )

    result = await session.chat("hello")

    assert result == "nudge response"
    assert before_response_contents == ["nudge response"]


@pytest.mark.asyncio
async def test_before_tool_hook_can_modify_tool_args():
    registry = FakeToolRegistry()
    session = make_session(FakeAgent(tool_registry=registry))

    async def rewrite_tool_args(ctx):
        assert ctx.session_id == "s1"
        assert ctx.agent_id == "fake-agent"
        assert ctx.state is session.state
        assert ctx.tool_name == "read"
        assert ctx.tool_args == {"path": "original.txt"}
        return HookResult.modify({"tool_args": {"path": "rewritten.txt"}})

    session.hooks.register(
        HookPoint.BEFORE_TOOL_CALL,
        rewrite_tool_args,
        name="rewrite_tool_args",
        permissions=HookPermissions(modify_tool_call=True),
    )

    await session._execute_tool_calls([
        {
            "id": "call_1",
            "function": {"name": "read", "arguments": '{"path":"original.txt"}'},
        }
    ])

    assert registry.calls == [("read", {"path": "rewritten.txt"})]


@pytest.mark.asyncio
async def test_after_tool_hook_can_modify_tool_result():
    registry = FakeToolRegistry(result="original result")
    session = make_session(FakeAgent(tool_registry=registry))

    async def rewrite_tool_result(ctx):
        assert ctx.tool_name == "read"
        assert ctx.tool_args == {"path": "a.txt"}
        assert ctx.tool_result == "original result"
        assert ctx.failed is False
        return HookResult.modify({"tool_result": "rewritten result"})

    session.hooks.register(
        HookPoint.AFTER_TOOL_CALL,
        rewrite_tool_result,
        name="rewrite_tool_result",
        permissions=HookPermissions(modify_tool_result=True),
    )

    await session._execute_tool_calls([
        {
            "id": "call_1",
            "function": {"name": "read", "arguments": '{"path":"a.txt"}'},
        }
    ])

    assert isinstance(session.state.messages[-1], ToolMessage)
    assert session.state.messages[-1].content == "rewritten result"


@pytest.mark.asyncio
async def test_before_tool_hook_can_skip_tool():
    registry = FakeToolRegistry()
    session = make_session(FakeAgent(tool_registry=registry))

    async def skip_tool(ctx):
        return HookResult.skip("skip from hook")

    session.hooks.register(
        HookPoint.BEFORE_TOOL_CALL,
        skip_tool,
        name="skip_tool",
        permissions=HookPermissions(skip_tool=True),
    )

    await session._execute_tool_calls([
        {
            "id": "call_1",
            "function": {"name": "read", "arguments": '{"path":"a.txt"}'},
        }
    ])

    assert registry.calls == []
    assert isinstance(session.state.messages[-1], ToolMessage)
    assert session.state.messages[-1].content == "Skipped: skip from hook"


@pytest.mark.asyncio
async def test_before_tool_hook_abort_adds_error_tool_message():
    registry = FakeToolRegistry()
    session = make_session(FakeAgent(tool_registry=registry))

    async def abort_tool(ctx):
        return HookResult.abort("abort from hook")

    session.hooks.register(
        HookPoint.BEFORE_TOOL_CALL,
        abort_tool,
        name="abort_tool",
        permissions=HookPermissions(abort_turn=True),
    )

    await session._execute_tool_calls([
        {
            "id": "call_1",
            "function": {"name": "read", "arguments": '{"path":"a.txt"}'},
        }
    ])

    assert registry.calls == []
    assert isinstance(session.state.messages[-1], ToolMessage)
    assert session.state.messages[-1].content == "Error: abort from hook"


@pytest.mark.asyncio
async def test_set_on_tool_call_still_receives_after_tool_event():
    registry = FakeToolRegistry(result="original result")
    session = make_session(FakeAgent(tool_registry=registry))
    seen: list[tuple[str, dict, str, bool]] = []

    async def rewrite_tool_result(ctx):
        return HookResult.modify({"result": "callback result"})

    session.hooks.register(
        HookPoint.AFTER_TOOL_CALL,
        rewrite_tool_result,
        name="rewrite_tool_result",
        permissions=HookPermissions(modify_tool_result=True),
    )
    session.set_on_tool_call(lambda name, args, result, failed: seen.append((name, args, result, failed)))

    await session._execute_tool_calls([
        {
            "id": "call_1",
            "function": {"name": "read", "arguments": '{"path":"a.txt"}'},
        }
    ])

    assert seen == [("read", {"path": "a.txt"}, "callback result", False)]
    assert session.state.messages[-1].content == "callback result"


@pytest.mark.asyncio
async def test_dynamic_read_only_classification_is_passed_to_guardrail_after_call():
    class DynamicReadOnlyTool:
        def is_action_read_only(self, args):
            return True

    registry = FakeToolRegistry(tools={"custom_dynamic_tool": DynamicReadOnlyTool()})
    session = make_session(FakeAgent(tool_registry=registry))
    captured: list[bool] = []

    class GuardrailDecision:
        is_warning = False
        is_halt = False

    def after_call(name, args, result, *, failed, is_read_only):
        captured.append(is_read_only)
        return GuardrailDecision()

    session._guardrail.after_call = after_call

    await session._execute_tool_calls([
        {
            "id": "call_1",
            "function": {"name": "custom_dynamic_tool", "arguments": '{"path":"a.txt"}'},
        }
    ])

    assert captured == [True]


@pytest.mark.asyncio
async def test_read_path_recall_memory_receives_session_state():
    registry = FakeToolRegistry()
    session = make_session(FakeAgent(tool_registry=registry))

    await session._execute_tool_calls([
        {
            "id": "call_1",
            "function": {"name": "recall_memory", "arguments": '{"query":"topic"}'},
        }
    ])

    assert registry.calls == [
        ("recall_memory", {"query": "topic", "_session_state": session.state})
    ]
