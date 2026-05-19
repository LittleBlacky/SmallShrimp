from __future__ import annotations
"""Ch14 主动消息 & Ch17 Cookie Agent 测试。"""
import pytest
from unittest.mock import AsyncMock, MagicMock


# ── post_message 工具测试 ──

def test_post_message_tool_no_channels():
    """无渠道时返回 None。"""
    from src.SmallShrimp.tools.post_message_tool import create_post_message_tool

    context = MagicMock()
    context.channels = []

    tool = create_post_message_tool(context)
    assert tool is None


def test_post_message_tool_with_channels():
    """有渠道时创建工具。"""
    from src.SmallShrimp.tools.post_message_tool import create_post_message_tool

    context = MagicMock()
    context.channels = [MagicMock()]
    context.eventbus = MagicMock()
    context.eventbus.publish = AsyncMock()

    tool = create_post_message_tool(context)
    assert tool is not None
    assert tool.name == "post_message"


@pytest.mark.asyncio
async def test_post_message_publishes_event():
    """post_message 发布 OutboundEvent。"""
    from src.SmallShrimp.tools.post_message_tool import create_post_message_tool

    context = MagicMock()
    context.channels = [MagicMock()]
    context.eventbus = MagicMock()
    context.eventbus.publish = AsyncMock()

    tool = create_post_message_tool(context)

    session = MagicMock()
    session.session_id = "test-session"
    session.agent = MagicMock()
    session.agent.agent_def = MagicMock()
    session.agent.agent_def.id = "pickle"

    result = await tool.call(content="任务已完成", session=session)
    assert "已发送" in result.content
    context.eventbus.publish.assert_called_once()


# ── Cookie Agent 加载测试 ──

def test_cookie_agent_exists():
    """Cookie agent 目录和文件存在。"""
    from pathlib import Path

    agent_dir = Path("workspace/agents/cookie")
    assert agent_dir.exists()
    assert (agent_dir / "AGENT.md").exists()
    assert (agent_dir / "SOUL.md").exists()


def test_cookie_agent_loader_loads():
    """AgentLoader 能加载 Cookie。"""
    from pathlib import Path
    from src.SmallShrimp.core.agent_loader import AgentLoader

    loader = AgentLoader(Path("workspace/agents"))
    cookie = loader.load("cookie")

    assert cookie.name == "Cookie"
    assert cookie.soul_md != ""


def test_agent_loader_discovers_cookie():
    """AgentLoader.discover_agents 包含 Cookie。"""
    from pathlib import Path
    from src.SmallShrimp.core.agent_loader import AgentLoader

    loader = AgentLoader(Path("workspace/agents"))
    agents = loader.discover_agents()

    names = [a.name for a in agents]
    assert "Cookie" in names
    assert "Pickle" in names


# ── MemoryManager 测试 ──

def test_memory_manager_remember():
    """MemoryManager.remember 持久化记忆。"""
    import tempfile
    from pathlib import Path
    from src.SmallShrimp.core.memory.memory_manager import TopicMemory

    with tempfile.TemporaryDirectory() as tmpdir:
        topics = TopicMemory(Path(tmpdir))
        record = topics.store("用户偏好 Python", tags=["preference"])

        assert record["content"] == "用户偏好 Python"
        assert "preference" in record["tags"]


def test_memory_manager_search():
    """MemoryManager search 检索记忆。"""
    import tempfile
    from pathlib import Path
    from src.SmallShrimp.core.memory.memory_manager import TopicMemory

    with tempfile.TemporaryDirectory() as tmpdir:
        topics = TopicMemory(Path(tmpdir))
        topics.store("用户偏好 dark mode")
        topics.store("项目名叫 SmallShrimp")

        results = topics.search("dark")
        assert len(results) == 1
        assert "dark mode" in results[0]["content"]

        results = topics.search("")
        assert len(results) == 2


if __name__ == "__main__":
    import asyncio
    test_post_message_tool_no_channels()
    test_post_message_tool_with_channels()
    asyncio.run(test_post_message_publishes_event())
    test_cookie_agent_exists()
    test_cookie_agent_loader_loads()
    test_agent_loader_discovers_cookie()
    test_memory_manager_remember()
    test_memory_manager_recall()
    print("\nAll Ch14+Ch17 tests passed!")
