"""端到端记忆集成测试 — 合并后的 pinned 模型。"""
import tempfile
from pathlib import Path
import pytest
from src.SmallShrimp.core.memory.memory_manager import MemoryManager
from src.SmallShrimp.core.message import SystemMessage, HumanMessage


@pytest.fixture
def memory():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield MemoryManager(Path(tmpdir))


class TestMemoryE2E:
    def test_pinned_vs_normal(self, memory):
        """pinned 记忆进 system prompt 且不淘汰。"""
        memory.remember("用户叫 Zane", pinned=True)
        memory.remember("用户喜欢 Python")
        pinned = memory.get_pinned()
        assert any("Zane" in r["content"] for r in pinned)
        assert not any("Python" in r["content"] for r in pinned)

    def test_pinned_update_via_dedup(self, memory):
        """改名后 pinned 自动覆盖。"""
        r1 = memory.remember("用户叫 Zane", pinned=True)
        r2 = memory.remember("用户叫 Zaner", pinned=True)
        pinned = memory.get_pinned()
        assert len(pinned) == 1
        assert pinned[0]["id"] == r1["id"]
        assert "Zaner" in pinned[0]["content"]

    def test_recall_count(self, memory):
        """热门记忆 recall_count 更高。"""
        memory.remember("用户喜欢 Python")
        memory.remember("午餐吃了面条")
        for _ in range(5):
            memory.recall("Python")
        all_r = memory.topics.list_all()
        py = next(r for r in all_r if "Python" in r["content"])
        noodle = next(r for r in all_r if "面条" in r["content"])
        assert py.get("recall_count", 0) > noodle.get("recall_count", 0)

    def test_inject_memories(self, memory):
        memory.remember("用户喜欢 Python")
        msgs = [SystemMessage(content="你是助手"), HumanMessage(content="Hi")]
        result = memory.inject_memories(msgs, query="Python")
        assert len(result) >= 2

    def test_lru_protects_pinned(self, memory):
        """pinned 记忆不被淘汰。"""
        memory.remember("关键画像", pinned=True)
        for i in range(50):
            memory.remember(f"冷门{i}")
        pinned = memory.get_pinned()
        assert any("关键画像" in r["content"] for r in pinned)

    def test_cross_session(self, memory):
        """跨会话持久化。"""
        memory.remember("用户喜欢 Python")
        memory.remember("用户叫 Zane", pinned=True)
        new_mem = MemoryManager(memory.memory_dir)
        assert any("Python" in r["content"] for r in new_mem.recall("Python"))
        assert any("Zane" in r["content"] for r in new_mem.get_pinned())
