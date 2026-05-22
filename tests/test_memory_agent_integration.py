"""Agent 层记忆集成测试 — 合并后的 pinned 模型。"""
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
    for t in create_memory_tools(mem):
        toolbox.register(t)


@pytest.fixture
def toolbox():
    from src.SmallShrimp.tools.registry import ToolRegistry
    return ToolRegistry()


@pytest.fixture
def setup():
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        mem = MemoryManager(ws / "memories")
        pb = PromptBuilder(ws)
        yield mem, pb


class TestPrompt:
    def test_pinned_in_prompt(self, setup, toolbox):
        mem, pb = setup
        mem.remember("用户叫 Zane", pinned=True)
        agent = _make_agent(mem, toolbox)
        state = SessionState(session_id="x", agent=agent, prompt_builder=pb)
        content = state.build_messages()[0]["content"]
        assert "Zane" in content
        assert "记忆指南" in content

    def test_layer_order(self, setup, toolbox):
        mem, pb = setup
        mem.remember("用户叫 Zane", pinned=True)
        agent = _make_agent(mem, toolbox)
        state = SessionState(session_id="x", agent=agent, prompt_builder=pb)
        content = state.build_messages()[0]["content"]
        assert content.find("记忆") < content.find("记忆指南")


class TestTools:
    @pytest.mark.asyncio
    async def test_recall(self, setup, toolbox):
        mem, _ = setup
        _register(mem, toolbox)
        mem.remember("用户喜欢 Python")
        t = toolbox.get("recall_memory")
        r = await t.call(query="Python")
        assert r.success and "Python" in r.content

    @pytest.mark.asyncio
    async def test_remember_pinned(self, setup, toolbox):
        mem, _ = setup
        _register(mem, toolbox)
        t = toolbox.get("remember")
        r = await t.call(content="用户叫 Zane", pinned=True)
        assert r.success and "已记住" in r.content
        assert any("Zane" in x["content"] for x in mem.get_pinned())

    @pytest.mark.asyncio
    async def test_remember_plain(self, setup, toolbox):
        mem, _ = setup
        _register(mem, toolbox)
        t = toolbox.get("remember")
        r = await t.call(content="用户喜欢 Rust")
        assert r.success
        assert any("Rust" in x["content"] for x in mem.recall("Rust"))

    @pytest.mark.asyncio
    async def test_schemas(self, setup, toolbox):
        mem, _ = setup
        _register(mem, toolbox)
        names = {s["function"]["name"] for s in toolbox.get_schemas()}
        assert "recall_memory" in names
        assert "remember" in names


class TestE2E:
    def test_cross_session(self, setup, toolbox):
        mem, _ = setup
        mem.remember("用户叫 Zane", pinned=True)
        mem.remember("喜欢 Python")
        new_mem = MemoryManager(mem.memory_dir)
        assert any("Zane" in r["content"] for r in new_mem.get_pinned())
        assert any("Python" in r["content"] for r in new_mem.recall("Python"))

    @pytest.mark.asyncio
    async def test_discover_then_remember(self, setup, toolbox):
        mem, _ = setup
        _register(mem, toolbox)
        recall = toolbox.get("recall_memory")
        remember = toolbox.get("remember")
        r = await recall.call(query="跑步")
        await remember.call(content="用户喜欢跑步")
        r = await recall.call(query="跑步")
        assert "跑步" in r.content
