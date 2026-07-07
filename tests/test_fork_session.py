from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.SmallShrimp.core.hooks import HookManager, HookPoint, HookResult
from src.SmallShrimp.core.commands.handlers import CommandContext, cmd_fork
from src.SmallShrimp.core.runtime.fork import ForkOptions, fork_session
from src.SmallShrimp.core.runtime.message import AssistantMessage, HumanMessage
from src.SmallShrimp.core.runtime.session_state import SessionState


class FakeAgent:
    def __init__(self):
        self.agent_def = SimpleNamespace(id="pickle", name="pickle")
        self.history_manager = None


def test_fork_session_copies_recent_context_into_new_session():
    agent = FakeAgent()
    parent_state = SessionState(
        session_id="parent-session",
        agent=agent,
        messages=[
            HumanMessage(content="第一条不用带入"),
            HumanMessage(content="整理项目结构"),
            AssistantMessage(content="已完成 src 分层并跑测试"),
        ],
    )
    parent = SimpleNamespace(agent=agent, state=parent_state)

    forked = fork_session(parent, ForkOptions(max_messages=2))

    assert forked.session_id != parent_state.session_id
    assert [m.content for m in forked.messages] == [
        "整理项目结构",
        "已完成 src 分层并跑测试",
    ]
    assert forked.parent_session_id == "parent-session"
    assert forked.agent_id == "pickle"


def test_fork_session_persists_when_history_manager_exists(tmp_path):
    from src.SmallShrimp.core.history import HistoryManager

    agent = FakeAgent()
    agent.history_manager = HistoryManager(tmp_path)
    parent_state = SessionState(
        session_id="parent-session",
        agent=agent,
        messages=[HumanMessage(content="把这个流程 fork 给子 agent")],
    )
    parent = SimpleNamespace(agent=agent, state=parent_state)

    forked = fork_session(parent, ForkOptions(task="根据上下文创建 skill"))

    session_file = Path(tmp_path) / f"{forked.session_id}.json"
    assert session_file.exists()
    assert "根据上下文创建 skill" in session_file.read_text(encoding="utf-8")


def test_cmd_fork_returns_new_session_id():
    agent = FakeAgent()
    state = SessionState(
        session_id="parent-session",
        agent=agent,
        messages=[HumanMessage(content="当前任务上下文")],
    )
    context = CommandContext(session=SimpleNamespace(agent=agent, state=state))

    result = asyncio.run(cmd_fork(context, ["请子 agent 总结方法论"]))

    assert "已 fork 新会话" in result
    assert "parent-session" in result
    assert "请子 agent 总结方法论" in result


@pytest.mark.asyncio
async def test_fork_session_emits_fork_created_when_hooks_available():
    agent = FakeAgent()
    parent_state = SessionState(
        session_id="parent-session",
        agent=agent,
        messages=[HumanMessage(content="当前任务上下文")],
    )
    parent = SimpleNamespace(agent=agent, state=parent_state, hooks=HookManager())
    seen = []

    async def record(ctx):
        seen.append(ctx)
        return HookResult.observe()

    parent.hooks.register(HookPoint.FORK_CREATED, record, name="record_fork")

    forked = fork_session(parent, ForkOptions(task="创建复盘摘要"))
    await asyncio.sleep(0)

    assert len(seen) == 1
    assert seen[0].hook_point == HookPoint.FORK_CREATED
    assert seen[0].session_id == forked.session_id
    assert seen[0].parent_session_id == "parent-session"
    assert seen[0].agent_id == "pickle"
    assert seen[0].state is parent_state
    assert seen[0].metadata == {"task": "创建复盘摘要"}


def test_fork_hook_failure_does_not_prevent_return_or_persistence(tmp_path):
    from src.SmallShrimp.core.history import HistoryManager

    agent = FakeAgent()
    agent.history_manager = HistoryManager(tmp_path)
    parent_state = SessionState(
        session_id="parent-session",
        agent=agent,
        messages=[HumanMessage(content="需要 fork 的上下文")],
    )
    parent = SimpleNamespace(agent=agent, state=parent_state, hooks=HookManager())

    async def broken(ctx):
        raise RuntimeError("hook failed")

    parent.hooks.register(HookPoint.FORK_CREATED, broken, name="broken", critical=True)

    forked = fork_session(parent, ForkOptions(task="失败也要持久化"))

    session_file = Path(tmp_path) / f"{forked.session_id}.json"
    assert forked.parent_session_id == "parent-session"
    assert session_file.exists()
    assert "失败也要持久化" in session_file.read_text(encoding="utf-8")
