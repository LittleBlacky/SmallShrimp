"""Memory 模块完整测试 - LayeredMemoryStore, ProjectMemory, DailyNotes, MemoryManager。"""
import tempfile
from pathlib import Path
from datetime import date

from src.SmallShrimp.core.memory.memory_manager import LayeredMemoryStore, ProjectMemory, DailyNotes, MemoryManager


def test_layer_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = LayeredMemoryStore(Path(tmpdir), "facts")
        record = store.store("用户偏好 Python")
        assert record["content"] == "用户偏好 Python"
        assert record["layer"] == "facts"
        assert "id" in record


def test_layer_search_by_keyword():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = LayeredMemoryStore(Path(tmpdir), "facts")
        store.store("用户喜欢 dark mode")
        store.store("项目名叫 SmallShrimp")
        store.store("用户偏好 Python")
        results = store.search("python")
        assert len(results) == 1
        assert "Python" in results[0]["content"]


def test_layer_search_limit():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = LayeredMemoryStore(Path(tmpdir), "facts")
        for index in range(5):
            store.store(f"记忆{index}")
        assert len(store.search("", limit=3)) == 3


def test_layer_delete():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = LayeredMemoryStore(Path(tmpdir), "facts")
        record = store.store("待删除")
        assert store.delete(record["id"]) is True
        assert store.delete(record["id"]) is False


def test_layer_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        store = LayeredMemoryStore(root, "facts")
        store.store("持久化内容")
        new_store = LayeredMemoryStore(root, "facts")
        assert new_store.list_all()[0]["content"] == "持久化内容"


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


def test_memory_manager_list_delete_consolidate():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))
        manager.remember_fact("用户喜欢 Python")
        duplicate = manager.remember_fact("喜欢 Python")
        assert len(manager.list_all(["facts"])) == 1
        assert manager.delete(duplicate["id"])
        assert manager.list_all(["facts"]) == []


def test_memory_manager_project_update_and_note():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))
        manager.project_update("test", "status", "active")
        assert manager.projects.load_project("test")["status"] == "active"
        manager.today_note("今日笔记")
        assert "今日笔记" in manager.daily.read_note()
