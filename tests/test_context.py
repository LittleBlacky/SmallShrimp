from __future__ import annotations
"""Context 测试。"""
from pathlib import Path
from unittest.mock import MagicMock


def _write_minimal_workspace(ws: Path) -> None:
    (ws / "config.user.yaml").write_text(
        "default_provider: deepseek\nproviders:\n  deepseek:\n    api_key: test\n    api_base: https://api.deepseek.com\n",
        encoding="utf-8",
    )
    agent_dir = ws / "agents" / "pickle"
    agent_dir.mkdir(parents=True)
    (agent_dir / "AGENT.md").write_text(
        "---\nname: Pickle\ndescription: Test\nllm:\n  provider: deepseek\n  model: deepseek/deepseek-chat\n---\n\n# Pickle\n",
        encoding="utf-8",
    )
    (ws / "skills").mkdir()
    (ws / "sessions").mkdir()
    (ws / "memories").mkdir()


def test_context_from_workspace(workspace_tmp):
    """测试从工作区创建 Context。"""
    from src.SmallShrimp.server.context import Context

    _write_minimal_workspace(workspace_tmp)
    context = Context.from_workspace(workspace_tmp)
    try:
        assert context.config is not None
        assert context.agent_loader is not None
        assert context.skill_loader is not None
        assert context.history_manager is not None
        assert context.tool_registry is not None
        assert context.eventbus is not None
        assert context.command_registry is not None
        assert context.prompt_builder is not None
        assert context.memory_manager is not None
        assert context.channels == []
    finally:
        context.close()


def test_context_dataclass_manual():
    """测试手动创建 Context dataclass。"""
    from src.SmallShrimp.server.context import Context

    config = MagicMock()
    agent_loader = MagicMock()
    skill_loader = MagicMock()
    history_manager = MagicMock()
    tool_registry = MagicMock()
    eventbus = MagicMock()
    command_registry = MagicMock()
    prompt_builder = MagicMock()
    memory_manager = MagicMock()
    cron_loader = MagicMock()

    context = Context(
        config=config,
        agent_loader=agent_loader,
        skill_loader=skill_loader,
        history_manager=history_manager,
        tool_registry=tool_registry,
        eventbus=eventbus,
        command_registry=command_registry,
        prompt_builder=prompt_builder,
        memory_manager=memory_manager,
        cron_loader=cron_loader,
    )

    assert context.agent_loader is agent_loader
    assert context.eventbus is eventbus
    assert context.workspace == Path("workspace")
    assert context.channels == []
    assert context.websocket_worker is None


def test_context_agent_receives_memory_manager_in_prompt(workspace_tmp):
    """Context 创建的 Agent 必须共享 memory_manager，否则 User Profile 不会进入 prompt。"""
    from src.SmallShrimp.core.agent import Agent
    from src.SmallShrimp.server.context import Context

    _write_minimal_workspace(workspace_tmp)
    context = Context.from_workspace(workspace_tmp)
    try:
        context.memory_manager.remember_profile("我叫zane")
        agent_def = context.agent_loader.load("pickle")
        agent = Agent(
            agent_def,
            context.config,
            context.tool_registry,
            context.history_manager,
            prompt_builder=context.prompt_builder,
            memory_manager=context.memory_manager,
        )
        session = agent.new_session()

        system_prompt = session.state.build_messages()[0]["content"]
        assert agent.memory_manager is context.memory_manager
        assert "## User Profile" in system_prompt
        assert "我叫zane" in system_prompt
    finally:
        context.close()


if __name__ == "__main__":
    raise SystemExit("Run with pytest")

