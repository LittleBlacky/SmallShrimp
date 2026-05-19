from __future__ import annotations
"""SharedContext 测试。"""
import pytest
from unittest.mock import MagicMock
from pathlib import Path


def test_shared_context_init():
    """测试 SharedContext 初始化。"""
    from src.SmallShrimp.core.context import SharedContext

    config = MagicMock()
    config.get = MagicMock(return_value="workspace/sessions")
    config.get_provider_config = MagicMock(return_value={"api_key": "test"})

    context = SharedContext(config)

    assert context.agent_loader is not None
    assert context.skill_loader is not None
    assert context.eventbus is not None
    assert context.prompt_builder is not None
    assert context.command_registry is not None


def test_shared_context_default_channels():
    """测试默认 channels 为空列表。"""
    from src.SmallShrimp.core.context import SharedContext

    config = MagicMock()
    config.get = MagicMock(return_value="workspace/sessions")

    context = SharedContext(config)
    assert context.channels == []


def test_shared_context_custom_channels():
    """测试自定义 channels。"""
    from src.SmallShrimp.core.context import SharedContext

    config = MagicMock()
    config.get = MagicMock(return_value="workspace/sessions")

    channel = MagicMock()
    context = SharedContext(config, channels=[channel])
    assert len(context.channels) == 1
    assert context.channels[0] is channel


def test_subscribe():
    """测试事件订阅。"""
    from src.SmallShrimp.core.context import SharedContext
    from src.SmallShrimp.core.events import OutboundEvent

    config = MagicMock()
    config.get = MagicMock(return_value="workspace/sessions")

    context = SharedContext(config)

    handler = MagicMock()
    context.subscribe(OutboundEvent, handler)

    assert OutboundEvent in context.eventbus._subscribers


def test_publish():
    """测试事件发布。"""
    from src.SmallShrimp.core.context import SharedContext
    from src.SmallShrimp.core.events import OutboundEvent, CliEventSource

    config = MagicMock()
    config.get = MagicMock(return_value="workspace/sessions")

    context = SharedContext(config)

    async def run_test():
        event = OutboundEvent(session_id="test", source=CliEventSource(), content="test content")
        await context.publish(event)

    import asyncio
    asyncio.run(run_test())


if __name__ == "__main__":
    test_shared_context_init()
    test_shared_context_default_channels()
    test_shared_context_custom_channels()
    test_subscribe()
    print("\nAll test_context tests passed!")