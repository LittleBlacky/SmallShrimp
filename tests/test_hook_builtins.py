from __future__ import annotations

import json

import pytest

from src.SmallShrimp.core.hook_builtins import register_builtin_hooks
from src.SmallShrimp.core.hooks import HookContext, HookManager, HookPoint
from src.SmallShrimp.core.runtime.agent import AgentSession
from src.SmallShrimp.core.runtime.session_state import SessionState


class FakeAgentDef:
    id = "fake-agent"
    name = "fake"
    llm = {"context_window": 10000}
    metadata: dict = {}


class FakeConfig:
    def __init__(self, hooks_config=None):
        self.data = {"workspace": "workspace"}
        if hooks_config is not None:
            self.data["hooks"] = hooks_config

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
    def get_schemas(self, active_only=True):
        return []


class FakeTrustManager:
    def is_trusted(self, cwd):
        return True

    def scan_dangerous(self, cwd):
        return []


class FakeLLM:
    thinking_strategy = None

    async def chat(self, messages, tools=None, reasoning_content=None):
        return {
            "content": "response",
            "finish_reason": "stop",
            "tool_calls": None,
            "reasoning_content": None,
            "should_store_reasoning": False,
        }


class FakeAgent:
    def __init__(self, hooks_config=None):
        self.agent_def = FakeAgentDef()
        self.config = FakeConfig(hooks_config)
        self.context_guard = FakeContextGuard()
        self.tool_registry = FakeToolRegistry()
        self.history_manager = None
        self.memory_manager = None
        self.pattern_learner = FakePatternLearner()
        self.trust_manager = FakeTrustManager()
        self.llm = FakeLLM()
        self._mcp_registered = True


@pytest.mark.asyncio
async def test_register_builtin_audit_log_from_config(tmp_path):
    log_path = tmp_path / "audit.log"
    manager = HookManager()

    loaded = register_builtin_hooks(
        manager,
        {
            "enabled": True,
            "builtin": {
                "audit_log": {
                    "enabled": True,
                    "point": "tool.after_call",
                    "path": str(log_path),
                }
            },
        },
    )

    result = await manager.run(
        HookContext(
            hook_point=HookPoint.AFTER_TOOL_CALL,
            session_id="s1",
            agent_id="a1",
            tool_name="read_file",
            failed=False,
        )
    )

    assert loaded == ["audit_log"]
    assert result.action == "observe"
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert record["hook_point"] == "tool.after_call"
    assert record["session_id"] == "s1"
    assert record["agent_id"] == "a1"
    assert record["tool_name"] == "read_file"
    assert record["failed"] is False


def test_register_builtin_hooks_ignores_disabled_and_unknown(tmp_path):
    manager = HookManager()

    loaded = register_builtin_hooks(
        manager,
        {
            "enabled": True,
            "builtin": {
                "audit_log": {"enabled": False, "path": str(tmp_path / "audit.log")},
                "unknown_hook": {"enabled": True},
            },
        },
    )

    assert loaded == []
    assert manager.list_hooks() == []
    assert register_builtin_hooks(HookManager(), None) == []
    assert register_builtin_hooks(HookManager(), {"enabled": False}) == []
    assert register_builtin_hooks(HookManager(), True) == []
    assert register_builtin_hooks(HookManager(), []) == []
    assert register_builtin_hooks(HookManager(), "enabled") == []


def test_register_builtin_hooks_treats_bool_priority_as_default(tmp_path):
    manager = HookManager()

    loaded = register_builtin_hooks(
        manager,
        {
            "enabled": True,
            "builtin": {
                "audit_log": {
                    "enabled": True,
                    "point": "tool.after_call",
                    "path": str(tmp_path / "audit.log"),
                    "priority": True,
                }
            },
        },
    )

    hooks = manager.list_hooks(HookPoint.AFTER_TOOL_CALL)
    assert loaded == ["audit_log"]
    assert hooks[0].priority == 500


@pytest.mark.asyncio
async def test_register_builtin_skill_learning_stub_marks_metadata():
    manager = HookManager()

    loaded = register_builtin_hooks(
        manager,
        {
            "enabled": True,
            "builtin": {
                "skill_learning": {
                    "enabled": True,
                    "point": "task.completed",
                }
            },
        },
    )

    result = await manager.run(
        HookContext(
            hook_point=HookPoint.TASK_COMPLETED,
            session_id="s1",
            agent_id="a1",
            metadata={},
        )
    )

    assert loaded == ["skill_learning"]
    assert result.action == "observe"
    assert result.data == {"metadata": {"skill_learning_checked": True}}
    assert result.message == "skill learning checked"


def test_agent_session_registers_builtin_hooks_from_agent_config(tmp_path):
    hooks_config = {
        "enabled": True,
        "builtin": {
            "audit_log": {
                "enabled": True,
                "point": "tool.after_call",
                "path": str(tmp_path / "audit.log"),
            }
        },
    }
    agent = FakeAgent(hooks_config)
    state = SessionState(session_id="s1", agent=agent, messages=[])

    session = AgentSession(agent=agent, state=state)

    hooks = session.hooks.list_hooks(HookPoint.AFTER_TOOL_CALL)
    assert [hook.name for hook in hooks] == ["builtin.audit_log"]
    assert hooks[0].source == "builtin"


def test_agent_session_ignores_malformed_hooks_config():
    agent = FakeAgent(True)
    state = SessionState(session_id="s1", agent=agent, messages=[])

    session = AgentSession(agent=agent, state=state)

    assert session.hooks.list_hooks() == []
