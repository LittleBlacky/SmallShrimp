"""端到端记忆集成测试 — 分层模型。"""
import tempfile
from pathlib import Path

import pytest

from src.SmallShrimp.core.memory.memory_manager import MemoryManager


@pytest.fixture
def memory():
    with tempfile.TemporaryDirectory() as tmpdir:
        mem = MemoryManager(Path(tmpdir))
        try:
            yield mem
        finally:
            mem.close()


class TestLayeredMemoryE2E:
    def test_profile_vs_task_memory(self, memory):
        memory.provider.store("profile", "用户叫 Zane")
        memory.provider.store("facts", "用户喜欢 Python")
        profile = memory.provider.list_all(layer="profile")
        assert any("Zane" in record["content"] for record in profile)
        assert not any("Python" in record["content"] for record in profile)

    def test_cross_session_persistence(self, memory):
        memory.provider.store("facts", "用户喜欢 Python")
        memory.provider.store("profile", "用户叫 Zane")
        new_mem = MemoryManager(memory.provider.memory_dir)
        try:
            assert any("Python" in record["content"] for record in new_mem.provider.search("Python", layer="facts"))
            assert any("Zane" in record["content"] for record in new_mem.provider.list_all(layer="profile"))
        finally:
            new_mem.close()

    def test_project_and_reflection_layers(self, memory):
        memory.provider.store("projects", "SmallShrimp 使用 pytest")
        memory.provider.store("reflections", "失败后先跑目标测试")
        assert any("pytest" in record["content"] for record in memory.provider.search("pytest", layer="projects"))
        assert any("目标测试" in record["content"] for record in memory.provider.search("测试", layer="reflections"))
