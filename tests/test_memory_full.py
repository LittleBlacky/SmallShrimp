"""Memory 模块完整测试 - _SQLiteLayerAdapter, ProjectMemory, DailyNotes, MemoryManager。"""
import tempfile
from pathlib import Path
from datetime import date

from src.SmallShrimp.core.memory.builtin.store import SQLiteBackend
from src.SmallShrimp.core.memory.builtin.provider import _SQLiteLayerAdapter
from src.SmallShrimp.core.memory.memory_manager import ProjectMemory, DailyNotes, MemoryManager


def _layer_store(tmpdir: str, layer: str) -> tuple:
    """Helper to create a per-layer store. Returns (adapter, backend)."""
    backend = SQLiteBackend(Path(tmpdir) / "memory.db")
    return _SQLiteLayerAdapter(backend, layer), backend


def _with_store(tmpdir: str, layer: str, fn):
    """Run fn with a store and close backend afterwards."""
    adapter, backend = _layer_store(tmpdir, layer)
    try:
        return fn(adapter)
    finally:
        backend.close()


def test_layer_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        def _test(store):
            record = store.store("用户偏好 Python")
            assert record["content"] == "用户偏好 Python"
            assert record["layer"] == "facts"
            assert "id" in record
        _with_store(tmpdir, "facts", _test)


def test_layer_search_by_keyword():
    with tempfile.TemporaryDirectory() as tmpdir:
        def _test(store):
            store.store("用户喜欢 dark mode")
            store.store("项目名叫 SmallShrimp")
            store.store("用户偏好 Python")
            results = store.search("python")
            assert len(results) == 1
            assert "Python" in results[0]["content"]
        _with_store(tmpdir, "facts", _test)


def test_layer_search_limit():
    with tempfile.TemporaryDirectory() as tmpdir:
        def _test(store):
            for index in range(5):
                store.store(f"记忆{index}")
            assert len(store.search("", limit=3)) == 3
        _with_store(tmpdir, "facts", _test)


def test_layer_delete():
    with tempfile.TemporaryDirectory() as tmpdir:
        def _test(store):
            record = store.store("待删除")
            assert store.delete(record["id"]) is True
            assert store.delete(record["id"]) is False
        _with_store(tmpdir, "facts", _test)


def test_layer_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter1, backend1 = _layer_store(tmpdir, "facts")
        adapter1.store("持久化内容")
        backend1.close()
        adapter2, backend2 = _layer_store(tmpdir, "facts")
        assert adapter2.list_all()[0]["content"] == "持久化内容"
        backend2.close()


def test_project_memory_full():
    with tempfile.TemporaryDirectory() as tmpdir:
        projects = ProjectMemory(Path(tmpdir))
        projects.save_project("test", {"id": "test", "language": "Python"})
        assert projects.load_project("test")["language"] == "Python"
        assert len(projects.list_projects()) == 1


def test_daily_notes_full():
    with tempfile.TemporaryDirectory() as tmpdir:
        notes = DailyNotes(Path(tmpdir))
        notes.write_note("今天完成测试", date(2024, 1, 15))
        assert "今天完成测试" in notes.read_note(date(2024, 1, 15))
        assert notes.list_notes(limit=5)[0]["date"] == "2024-01-15"


def test_memory_manager_remember_and_recall():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))
        try:
            profile = manager.remember_profile("用户叫 Zane")
            fact = manager.remember_fact("用户偏好 Python")
            project = manager.remember_project("SmallShrimp 使用 pytest")
            reflection = manager.remember_reflection("失败后先看测试")
            assert profile["layer"] == "profile"
            assert fact["layer"] == "facts"
            assert project["layer"] == "projects"
            assert reflection["layer"] == "reflections"
            assert not manager.recall("Zane")
            assert manager.recall("Python")
            assert manager.recall("pytest")
            assert manager.recall("测试")
        finally:
            manager.close()


def test_memory_manager_list_delete_consolidate():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))
        try:
            manager.remember_fact("用户喜欢 Python")
            duplicate = manager.remember_fact("喜欢 Python")
            assert len(manager.list_all(["facts"])) == 1
            assert manager.delete(duplicate["id"])
            assert manager.list_all(["facts"]) == []
        finally:
            manager.close()


def test_memory_manager_project_update_and_note():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))
        try:
            manager.project_update("smallshrimp", "language", "Python")
            assert manager.projects.load_project("smallshrimp")["language"] == "Python"
            manager.today_note("SQLite 迁移完成")
            assert "SQLite 迁移完成" in manager.daily.read_note()
        finally:
            manager.close()
        manager2 = MemoryManager(Path(tmpdir))
        try:
            manager2.project_update("test", "status", "active")
            assert manager2.projects.load_project("test")["status"] == "active"
            manager2.today_note("今日笔记")
            assert "今日笔记" in manager2.daily.read_note()
        finally:
            manager2.close()
