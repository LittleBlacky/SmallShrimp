from __future__ import annotations
"""Context 测试。"""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock


def test_context_from_workspace():
    """测试从工作区创建 Context。"""
    from src.SmallShrimp.server.context import Context

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "config.user.yaml").write_text("default_provider: openai\nproviders:\n  openai:\n    api_key: test\n")
        (ws / "agents").mkdir()
        (ws / "skills").mkdir()
        (ws / "sessions").mkdir()
        (ws / "memories").mkdir()

        context = Context.from_workspace(ws)

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


if __name__ == "__main__":
    test_context_from_workspace()
    test_context_dataclass_manual()
    print("\nAll test_context tests passed!")