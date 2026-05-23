"""端到端记忆集成测试 — 分层模型。"""
import tempfile
from pathlib import Path

import pytest

from src.SmallShrimp.core.memory.memory_manager import MemoryManager


@pytest.fixture
def memory():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield MemoryManager(Path(tmpdir))


class TestLayeredMemoryE2E:
    def test_profile_vs_task_memory(self, memory):
        memory.remember_profile("用户叫 Zane")
        memory.remember_fact("用户喜欢 Python")
        profile = memory.get_profile()
        assert any("Zane" in record["content"] for record in profile)
        assert not any("Python" in record["content"] for record in profile)
        assert not any("Zane" in record["content"] for record in memory.recall("Zane"))

    def test_profile_update_via_dedup(self, memory):
        first = memory.remember_profile("用户叫 Zane")
        second = memory.remember_profile("用户叫 Zaner")
        profile = memory.get_profile()
        assert len(profile) == 1
        assert profile[0]["id"] == first["id"] == second["id"]
        assert "Zaner" in profile[0]["content"]

    def test_consolidate_skips_profile(self, memory):
        memory.remember_profile("用户叫 Zane")
        memory.remember_fact("用户喜欢 Python")
        memory.remember_fact("喜欢 Python")
        merged = memory.consolidate()
        assert merged == 0
        assert len(memory.list_all(["facts"])) == 1
        assert len(memory.get_profile()) == 1

    def test_cross_session_persistence(self, memory):
        memory.remember_fact("用户喜欢 Python")
        memory.remember_profile("用户叫 Zane")
        new_memory = MemoryManager(memory.memory_dir)
        assert any("Python" in record["content"] for record in new_memory.recall("Python"))
        assert any("Zane" in record["content"] for record in new_memory.get_profile())

    def test_project_and_reflection_layers(self, memory):
        memory.remember_project("SmallShrimp 使用 pytest")
        memory.remember_reflection("失败后先跑目标测试")
        assert any("pytest" in record["content"] for record in memory.recall("pytest"))
        assert any("目标测试" in record["content"] for record in memory.recall("测试"))
