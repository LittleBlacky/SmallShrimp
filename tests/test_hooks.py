from __future__ import annotations

import pytest

from src.SmallShrimp.core.hooks import (
    HookContext,
    HookManager,
    HookPermissions,
    HookPoint,
    HookResult,
)


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

    result = await manager.run(
        HookContext(
            hook_point=HookPoint.MESSAGE_RECEIVED,
            session_id="s1",
            agent_id="a1",
            user_message="hello",
        )
    )

    assert result.action == "observe"
    assert calls == []


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
    assert result.data == {}


@pytest.mark.asyncio
async def test_observe_only_hook_cannot_mutate_context_in_place():
    manager = HookManager()
    context = HookContext(
        hook_point=HookPoint.BEFORE_TOOL_CALL,
        session_id="s1",
        agent_id="a1",
        user_message="original",
        messages=[{"role": "user", "content": "original"}],
        tool_args={"value": 1, "nested": {"keep": True}},
        metadata={"trace": ["original"], "nested": {"keep": True}},
    )

    async def handler(ctx):
        ctx.user_message = "changed"
        ctx.tool_args["value"] = 2
        ctx.tool_args["nested"]["keep"] = False
        ctx.messages.append({"role": "assistant", "content": "changed"})
        ctx.messages[0]["content"] = "changed"
        ctx.metadata["trace"].append("changed")
        ctx.metadata["nested"]["keep"] = False
        return HookResult.observe()

    manager.register(HookPoint.BEFORE_TOOL_CALL, handler, name="observe_only")

    result = await manager.run(context)

    assert result.action == "observe"
    assert context.user_message == "original"
    assert context.tool_args == {"value": 1, "nested": {"keep": True}}
    assert context.messages == [{"role": "user", "content": "original"}]
    assert context.metadata == {"trace": ["original"], "nested": {"keep": True}}


@pytest.mark.asyncio
async def test_non_critical_hook_exception_is_isolated_and_later_hook_runs():
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


@pytest.mark.asyncio
async def test_critical_hook_exception_is_reraised():
    manager = HookManager()

    async def broken(ctx):
        raise RuntimeError("boom")

    manager.register(HookPoint.AFTER_RESPONSE, broken, name="broken", critical=True)

    with pytest.raises(RuntimeError, match="boom"):
        await manager.run(
            HookContext(
                hook_point=HookPoint.AFTER_RESPONSE,
                session_id="s1",
                agent_id="a1",
                assistant_response="done",
            )
        )


@pytest.mark.asyncio
async def test_permitted_modify_on_before_response_returns_modify_result():
    manager = HookManager()

    async def handler(ctx):
        return HookResult.modify({"response": "changed"})

    manager.register(
        HookPoint.BEFORE_RESPONSE,
        handler,
        name="rewrite_response",
        permissions=HookPermissions(modify_response=True),
    )

    result = await manager.run(
        HookContext(
            hook_point=HookPoint.BEFORE_RESPONSE,
            session_id="s1",
            agent_id="a1",
            assistant_response="original",
        )
    )

    assert result.action == "modify"
    assert result.data == {"response": "changed"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("hook_result", "permissions"),
    [
        (HookResult.skip("skip"), HookPermissions()),
        (HookResult.abort("abort"), HookPermissions()),
        (HookResult(action="fork", data={"agent_id": "helper"}), HookPermissions()),
        (HookResult(action="enqueue", data={"task": "later"}), HookPermissions()),
    ],
)
async def test_unauthorized_skip_abort_fork_enqueue_are_ignored_as_observe(
    hook_result,
    permissions,
):
    manager = HookManager()

    async def handler(ctx):
        return hook_result

    manager.register(
        HookPoint.BEFORE_RESPONSE,
        handler,
        name="unauthorized",
        permissions=permissions,
    )

    result = await manager.run(
        HookContext(
            hook_point=HookPoint.BEFORE_RESPONSE,
            session_id="s1",
            agent_id="a1",
            assistant_response="original",
        )
    )

    assert result.action == "observe"
    assert result.data == {}


@pytest.mark.asyncio
async def test_before_tool_call_skip_is_allowed_when_skip_tool_permission_is_true():
    manager = HookManager()

    async def handler(ctx):
        return HookResult.skip("skip this tool")

    manager.register(
        HookPoint.BEFORE_TOOL_CALL,
        handler,
        name="skip_tool",
        permissions=HookPermissions(skip_tool=True),
    )

    result = await manager.run(
        HookContext(
            hook_point=HookPoint.BEFORE_TOOL_CALL,
            session_id="s1",
            agent_id="a1",
            tool_name="example",
            tool_args={"value": 1},
        )
    )

    assert result.action == "skip"
    assert result.message == "skip this tool"
