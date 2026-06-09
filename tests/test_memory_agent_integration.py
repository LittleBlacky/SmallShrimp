"""Agent 层记忆集成测试 — 分层记忆模型。"""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.SmallShrimp.core.memory.memory_manager import MemoryManager
from src.SmallShrimp.core.prompt_builder import PromptBuilder
from src.SmallShrimp.core.session_state import SessionState


def _make_agent(mem, toolbox):
    agent = MagicMock()
    agent.memory_manager = mem
    agent.tool_registry = toolbox
    agent.agent_def = MagicMock()
    agent.agent_def.id = "pickle"
    agent.agent_def.name = "Pickle"
    agent.agent_def.agent_md = "# Pickle\n\n你是 Pickle。"
    agent.agent_def.soul_md = ""
    agent.agent_def.guidelines = []
    agent.agent_def.instructions = []
    agent.agent_def.llm = {"context_window": 200000}
    return agent


def _register(mem, toolbox):
    from src.SmallShrimp.tools.memory_tool import create_memory_tools
    for tool in create_memory_tools(mem):
        toolbox.register(tool)


@pytest.fixture
def toolbox():
    from src.SmallShrimp.tools.registry import ToolRegistry
    return ToolRegistry()


@pytest.fixture
def setup():
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory)
        mem = MemoryManager(workspace / "memories")
        prompt_builder = PromptBuilder(workspace)
        yield mem, prompt_builder


class TestPrompt:
    def test_profile_in_prompt(self, setup, toolbox):
        mem, prompt_builder = setup
        mem.remember_profile("用户叫 Zane")
        mem.initialize("test-session")  # 初始化快照
        agent = _make_agent(mem, toolbox)
        state = SessionState(session_id="x", agent=agent, prompt_builder=prompt_builder)
        content = state.build_messages()[0]["content"]
        assert "User Profile" in content
        assert "Zane" in content

    def test_profile_placement(self, setup, toolbox):
        """Profile 位于 Bootstrap 之后、Channel 之前。"""
        mem, prompt_builder = setup
        mem.remember_profile("用户叫 Zane")
        mem.initialize("test-session")
        agent = _make_agent(mem, toolbox)
        state = SessionState(session_id="x", agent=agent, prompt_builder=prompt_builder)
        content = state.build_messages()[0]["content"]
        # Bootstrap 在前（此处为空），然后是 Profile
        assert "User Profile" in content


class TestTools:
    @pytest.mark.asyncio
    async def test_recall_excludes_profile(self, setup, toolbox):
        mem, _ = setup
        _register(mem, toolbox)
        mem.remember_profile("用户叫 Zane")
        mem.remember_fact("用户喜欢 Python")
        recall = toolbox.get("recall_memory")
        result = await recall.call(query="用户")
        assert result.success
        assert "Python" in result.content
        assert "Zane" not in result.content

    @pytest.mark.asyncio
    async def test_remember_profile(self, setup, toolbox):
        mem, _ = setup
        _register(mem, toolbox)
        tool = toolbox.get("remember_profile")
        result = await tool.call(content="用户叫 Zane")
        assert result.success and "用户画像" in result.content
        assert any("Zane" in record["content"] for record in mem.get_profile())

    @pytest.mark.asyncio
    async def test_remember_fact(self, setup, toolbox):
        mem, _ = setup
        _register(mem, toolbox)
        tool = toolbox.get("remember_fact")
        result = await tool.call(content="用户喜欢 Rust")
        assert result.success
        assert any("Rust" in record["content"] for record in mem.recall("Rust"))

    @pytest.mark.asyncio
    async def test_schemas(self, setup, toolbox):
        mem, _ = setup
        _register(mem, toolbox)
        names = {schema["function"]["name"] for schema in toolbox.get_schemas()}
        assert "recall_memory" in names
        assert "remember_profile" in names
        assert "remember_fact" in names
        assert "remember_project" in names
        assert "remember_reflection" in names


class TestE2E:
    def test_cross_session(self, setup, toolbox):
        mem, _ = setup
        mem.remember_profile("用户叫 Zane")
        mem.remember_fact("喜欢 Python")
        new_mem = MemoryManager(mem.memory_dir)
        assert any("Zane" in record["content"] for record in new_mem.get_profile())
        assert any("Python" in record["content"] for record in new_mem.recall("Python"))

    @pytest.mark.asyncio
    async def test_discover_then_remember(self, setup, toolbox):
        mem, _ = setup
        _register(mem, toolbox)
        recall = toolbox.get("recall_memory")
        remember = toolbox.get("remember_fact")
        result = await recall.call(query="跑步")
        assert "未找到" in result.content
        await remember.call(content="用户喜欢跑步")
        result = await recall.call(query="跑步")
        assert "跑步" in result.content
