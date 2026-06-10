from __future__ import annotations
"""Layered Memory Manager 测试。"""
import tempfile
from pathlib import Path

from src.SmallShrimp.core.memory import MemoryManager
from src.SmallShrimp.core.memory.memory_manager import ProjectMemory, _rank_memory
from src.SmallShrimp.core.memory.builtin.store import SQLiteBackend
from src.SmallShrimp.core.memory.builtin.provider import _SQLiteLayerAdapter
from src.SmallShrimp.core.message import HumanMessage, SystemMessage


def _layer_store(tmpdir: str, layer: str) -> tuple:
    """Helper to create a per-layer store. Returns (adapter, backend)."""
    backend = SQLiteBackend(Path(tmpdir) / "memory.db")
    return _SQLiteLayerAdapter(backend, layer), backend


def test_memory_manager_init():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))
        try:
            assert manager.memory_dir.exists()
            assert (manager.memory_dir / "memory.db").exists()
        finally:
            manager.close()


def test_layered_store_dedup_search_delete():
    with tempfile.TemporaryDirectory() as tmpdir:
        store, backend = _layer_store(tmpdir, "facts")
        try:
            first = store.store("用户喜欢 Python 编程")
            second = store.store("用户喜欢 Python 编程")
            assert second["id"] == first["id"]
            assert len(store.list_all()) == 1

            results = store.search("Python")
            assert len(results) == 1
            assert store.list_all()[0]["recall_count"] == 1

            assert store.delete(first["id"]) is True
            assert store.search("", limit=20) == []
        finally:
            backend.close()


def test_profile_is_separate_from_recall():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))
        try:
            manager.remember_profile("用户叫 Zane")
            manager.remember_fact("用户喜欢 Python")

            profile = manager.get_profile()
            assert any("Zane" in record["content"] for record in profile)
            assert not any("Zane" in record["content"] for record in manager.recall("Zane"))
            assert any("Python" in record["content"] for record in manager.recall("Python"))
        finally:
            manager.close()


def test_remember_routes_to_layers():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))
        try:
            assert manager.remember("长期偏好中文", layer="profile")["layer"] == "profile"
            assert manager.remember_fact("普通事实")["layer"] == "facts"
            assert manager.remember_project("项目使用 pytest")["layer"] == "projects"
            assert manager.remember_reflection("失败后先读测试")["layer"] == "reflections"
            assert manager.remember_session("本轮临时状态")["layer"] == "sessions"
        finally:
            manager.close()


def test_project_memory_state_api():
    with tempfile.TemporaryDirectory() as tmpdir:
        projects = ProjectMemory(Path(tmpdir))
        projects.save_project("test-project", {"id": "test-project", "language": "Python"})
        assert projects.load_project("test-project")["language"] == "Python"
        assert len(projects.list_projects()) == 1


def test_daily_notes_and_project_update():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))
        try:
            manager.project_update("smallshrimp", "language", "Python")
            assert manager.projects.load_project("smallshrimp")["language"] == "Python"
            manager.today_note("完成分层记忆重构")
            assert "完成分层记忆重构" in manager.daily.read_note()
        finally:
            manager.close()


def test_inject_memories_excludes_profile():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))
        try:
            manager.remember_profile("用户叫 Zane")
            manager.remember_fact("用户使用 DeepSeek API")
            messages = [SystemMessage(content="You are an assistant."), HumanMessage(content="Hello")]

            injected = manager.inject_memories(messages, query="DeepSeek")
            assert len(injected) == 3
            assert "Relevant Retrieved Memory" in injected[1].content
            assert "DeepSeek" in injected[1].content
            assert "Zane" not in injected[1].content
        finally:
            manager.close()


def test_memory_ranking():
    assert _rank_memory("dark mode", "dark mode preference") > 7.0
    assert _rank_memory("端口配置", "用户喜欢 Python 3.11") < 2.0
