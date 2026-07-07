from __future__ import annotations

import pytest

from src.SmallShrimp.core.hook_user_loader import UserHookConfig, load_user_hooks
from src.SmallShrimp.core.hooks import HookContext, HookManager, HookPoint
from src.SmallShrimp.core.runtime.agent import AgentSession
from src.SmallShrimp.core.runtime.session_state import SessionState


class FakeAgentDef:
    id = "fake-agent"
    name = "fake"
    llm = {"context_window": 10000}
    metadata: dict = {}


class FakeConfig:
    def __init__(self, workspace, hooks_config=None):
        self.data = {"workspace": str(workspace)}
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
    def __init__(self, workspace, hooks_config=None):
        self.agent_def = FakeAgentDef()
        self.config = FakeConfig(workspace, hooks_config)
        self.context_guard = FakeContextGuard()
        self.tool_registry = FakeToolRegistry()
        self.history_manager = None
        self.memory_manager = None
        self.pattern_learner = FakePatternLearner()
        self.trust_manager = FakeTrustManager()
        self.llm = FakeLLM()
        self._mcp_registered = True


def test_user_hook_loader_rejects_paths_outside_workspace(tmp_path):
    manager = HookManager()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("async def handle(ctx): return None", encoding="utf-8")

    loaded = load_user_hooks(
        manager,
        [
            UserHookConfig(
                name="outside",
                enabled=True,
                module=str(outside),
                handler="handle",
                point=HookPoint.BEFORE_RESPONSE.value,
            )
        ],
        workspace,
    )

    assert loaded == []
    assert manager.list_hooks(HookPoint.BEFORE_RESPONSE) == []


def test_user_hook_loader_rejects_traversal_path(tmp_path):
    manager = HookManager()
    workspace = tmp_path / "workspace"
    hooks_dir = workspace / "hooks"
    hooks_dir.mkdir(parents=True)
    outside = workspace / "outside.py"
    outside.write_text("async def handle(ctx): return None", encoding="utf-8")

    loaded = load_user_hooks(
        manager,
        [
            UserHookConfig(
                name="traversal",
                enabled=True,
                module="hooks/../outside.py",
                handler="handle",
                point=HookPoint.BEFORE_RESPONSE.value,
            )
        ],
        workspace,
    )

    assert loaded == []
    assert manager.list_hooks(HookPoint.BEFORE_RESPONSE) == []


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

    loaded = load_user_hooks(
        manager,
        [
            UserHookConfig(
                name="rewrite",
                enabled=True,
                module="hooks/rewrite.py",
                handler="handle",
                point=HookPoint.BEFORE_RESPONSE.value,
                permissions={"modify_response": True},
            )
        ],
        workspace,
    )

    result = await manager.run(
        HookContext(
            hook_point=HookPoint.BEFORE_RESPONSE,
            session_id="s1",
            agent_id="a1",
            assistant_response="original",
        )
    )

    assert loaded == ["rewrite"]
    assert result.action == "modify"
    assert result.data == {"response": "changed"}
    registered = manager.list_hooks(HookPoint.BEFORE_RESPONSE)
    assert registered[0].name == "user.rewrite"
    assert registered[0].source == "user"


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

    loaded = load_user_hooks(
        manager,
        [
            UserHookConfig(
                name="slow",
                enabled=True,
                module="hooks/slow.py",
                handler="handle",
                point=HookPoint.BEFORE_RESPONSE.value,
                timeout_ms=1,
            )
        ],
        workspace,
    )

    result = await manager.run(
        HookContext(
            hook_point=HookPoint.BEFORE_RESPONSE,
            session_id="s1",
            agent_id="a1",
            assistant_response="original",
        )
    )

    assert loaded == ["slow"]
    assert result.action == "observe"
    assert result.message == "user hook timed out"


def test_user_hook_loader_ignores_disabled_missing_non_python_and_invalid_point(tmp_path):
    manager = HookManager()
    workspace = tmp_path / "workspace"
    hooks_dir = workspace / "hooks"
    hooks_dir.mkdir(parents=True)
    text_file = hooks_dir / "not_python.txt"
    text_file.write_text("async def handle(ctx): return None", encoding="utf-8")
    valid_file = hooks_dir / "valid.py"
    valid_file.write_text("async def handle(ctx): return None", encoding="utf-8")

    loaded = load_user_hooks(
        manager,
        [
            UserHookConfig(
                name="disabled",
                enabled=False,
                module="hooks/valid.py",
                handler="handle",
                point=HookPoint.BEFORE_RESPONSE.value,
            ),
            UserHookConfig(
                name="missing",
                enabled=True,
                module="hooks/missing.py",
                handler="handle",
                point=HookPoint.BEFORE_RESPONSE.value,
            ),
            UserHookConfig(
                name="not_python",
                enabled=True,
                module="hooks/not_python.txt",
                handler="handle",
                point=HookPoint.BEFORE_RESPONSE.value,
            ),
            UserHookConfig(
                name="invalid_point",
                enabled=True,
                module="hooks/valid.py",
                handler="handle",
                point="not.a.point",
            ),
        ],
        workspace,
    )

    assert loaded == []
    assert manager.list_hooks() == []


@pytest.mark.asyncio
async def test_user_hook_loader_ignores_unknown_permission_keys(tmp_path):
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

    loaded = load_user_hooks(
        manager,
        [
            UserHookConfig(
                name="rewrite",
                enabled=True,
                module="hooks/rewrite.py",
                handler="handle",
                point=HookPoint.BEFORE_RESPONSE.value,
                permissions={"modify_response": True, "unknown": True},
            )
        ],
        workspace,
    )

    result = await manager.run(
        HookContext(
            hook_point=HookPoint.BEFORE_RESPONSE,
            session_id="s1",
            agent_id="a1",
            assistant_response="original",
        )
    )

    assert loaded == ["rewrite"]
    assert result.action == "modify"
    assert result.data == {"response": "changed"}


@pytest.mark.asyncio
async def test_sync_user_hook_handler_is_supported(tmp_path):
    workspace = tmp_path / "workspace"
    hooks_dir = workspace / "hooks"
    hooks_dir.mkdir(parents=True)
    hook_file = hooks_dir / "sync_hook.py"
    hook_file.write_text(
        "from src.SmallShrimp.core.hooks import HookResult\n"
        "def handle(ctx):\n"
        "    return HookResult.observe('sync observed')\n",
        encoding="utf-8",
    )
    manager = HookManager()

    loaded = load_user_hooks(
        manager,
        [
            UserHookConfig(
                name="sync_hook",
                enabled=True,
                module="hooks/sync_hook.py",
                handler="handle",
                point=HookPoint.BEFORE_RESPONSE.value,
            )
        ],
        workspace,
    )

    result = await manager.run(
        HookContext(
            hook_point=HookPoint.BEFORE_RESPONSE,
            session_id="s1",
            agent_id="a1",
            assistant_response="original",
        )
    )

    assert loaded == ["sync_hook"]
    assert result.action == "observe"
    assert result.message == "sync observed"


def test_agent_session_registers_user_hooks_from_agent_config(tmp_path):
    workspace = tmp_path / "workspace"
    hooks_dir = workspace / "hooks"
    hooks_dir.mkdir(parents=True)
    hook_file = hooks_dir / "quality_gate.py"
    hook_file.write_text(
        "from src.SmallShrimp.core.hooks import HookResult\n"
        "async def handle(ctx):\n"
        "    return HookResult.observe('checked')\n",
        encoding="utf-8",
    )
    hooks_config = {
        "enabled": True,
        "user": {
            "quality_gate": {
                "enabled": True,
                "module": "hooks/quality_gate.py",
                "handler": "handle",
                "point": "response.before",
                "priority": 250,
            }
        },
    }
    agent = FakeAgent(workspace, hooks_config)
    state = SessionState(session_id="s1", agent=agent, messages=[])

    session = AgentSession(agent=agent, state=state)

    hooks = session.hooks.list_hooks(HookPoint.BEFORE_RESPONSE)
    assert [hook.name for hook in hooks] == ["user.quality_gate"]
    assert hooks[0].source == "user"
    assert hooks[0].priority == 250


def test_agent_session_ignores_malformed_user_hooks_config(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "hooks").mkdir(parents=True)
    hooks_config = {"enabled": True, "user": ["not", "a", "mapping"]}
    agent = FakeAgent(workspace, hooks_config)
    state = SessionState(session_id="s1", agent=agent, messages=[])

    session = AgentSession(agent=agent, state=state)

    assert session.hooks.list_hooks() == []
