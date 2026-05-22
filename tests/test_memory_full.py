from __future__ import annotations
"""Memory 模块完整测试 - TopicMemory, ProjectMemory, DailyNotes, MemoryManager。"""
import tempfile
from pathlib import Path
from datetime import date


# ── TopicMemory ──

def test_topic_store():
    """存储记忆并返回记录。"""
    from src.SmallShrimp.core.memory.memory_manager import TopicMemory

    with tempfile.TemporaryDirectory() as tmpdir:
        topics = TopicMemory(Path(tmpdir))
        record = topics.store("用户偏好 Python")
        assert record["content"] == "用户偏好 Python"
        assert "id" in record


def test_topic_search_by_keyword():
    """按关键词搜索。"""
    from src.SmallShrimp.core.memory.memory_manager import TopicMemory

    with tempfile.TemporaryDirectory() as tmpdir:
        topics = TopicMemory(Path(tmpdir))
        topics.store("用户喜欢 dark mode")
        topics.store("项目名叫 SmallShrimp")
        topics.store("用户偏好 Python")

        results = topics.search("python")
        assert len(results) == 1
        assert "Python" in results[0]["content"]


def test_topic_search_limit():
    """限制返回数量。"""
    from src.SmallShrimp.core.memory.memory_manager import TopicMemory

    with tempfile.TemporaryDirectory() as tmpdir:
        topics = TopicMemory(Path(tmpdir))
        for i in range(5):
            topics.store(f"记忆{i}")

        results = topics.search("", limit=3)
        assert len(results) == 3


def test_topic_update():
    """更新记忆内容。"""
    from src.SmallShrimp.core.memory.memory_manager import TopicMemory

    with tempfile.TemporaryDirectory() as tmpdir:
        topics = TopicMemory(Path(tmpdir))
        record = topics.store("旧内容")
        updated = topics.update(record["id"], content="新内容")
        assert updated is not None
        assert updated["content"] == "新内容"


def test_topic_update_nonexistent():
    """更新不存在的记录返回 None。"""
    from src.SmallShrimp.core.memory.memory_manager import TopicMemory

    with tempfile.TemporaryDirectory() as tmpdir:
        topics = TopicMemory(Path(tmpdir))
        assert topics.update("nonexistent", content="x") is None


def test_topic_delete():
    """删除记忆。"""
    from src.SmallShrimp.core.memory.memory_manager import TopicMemory

    with tempfile.TemporaryDirectory() as tmpdir:
        topics = TopicMemory(Path(tmpdir))
        record = topics.store("待删除")
        assert topics.delete(record["id"]) is True
        assert topics.delete(record["id"]) is False  # 已删除


def test_topic_list_all():
    """列出所有记忆。"""
    from src.SmallShrimp.core.memory.memory_manager import TopicMemory

    with tempfile.TemporaryDirectory() as tmpdir:
        topics = TopicMemory(Path(tmpdir))
        topics.store("A")
        topics.store("B")
        assert len(topics.list_all()) == 2


# ── ProjectMemory ──

def test_project_save_and_load():
    """保存和加载项目。"""
    from src.SmallShrimp.core.memory.memory_manager import ProjectMemory

    with tempfile.TemporaryDirectory() as tmpdir:
        projects = ProjectMemory(Path(tmpdir))
        projects.save_project("smallshrimp", {"name": "SmallShrimp", "status": "开发中"})

        loaded = projects.load_project("smallshrimp")
        assert loaded is not None
        assert loaded["name"] == "SmallShrimp"
        assert loaded["status"] == "开发中"


def test_project_list():
    """列出所有项目。"""
    from src.SmallShrimp.core.memory.memory_manager import ProjectMemory

    with tempfile.TemporaryDirectory() as tmpdir:
        projects = ProjectMemory(Path(tmpdir))
        projects.save_project("proj-a", {"name": "A"})
        projects.save_project("proj-b", {"name": "B"})

        result = projects.list_projects()
        assert len(result) == 2


def test_project_delete():
    """删除项目。"""
    from src.SmallShrimp.core.memory.memory_manager import ProjectMemory

    with tempfile.TemporaryDirectory() as tmpdir:
        projects = ProjectMemory(Path(tmpdir))
        projects.save_project("temp", {"name": "Temp"})
        assert projects.delete_project("temp") is True
        assert projects.load_project("temp") is None


def test_project_load_nonexistent():
    """加载不存在的项目返回 None。"""
    from src.SmallShrimp.core.memory.memory_manager import ProjectMemory

    with tempfile.TemporaryDirectory() as tmpdir:
        projects = ProjectMemory(Path(tmpdir))
        assert projects.load_project("nonexistent") is None


# ── DailyNotes ──

def test_daily_write_and_read():
    """写入和读取每日笔记。"""
    from src.SmallShrimp.core.memory.memory_manager import DailyNotes

    with tempfile.TemporaryDirectory() as tmpdir:
        daily = DailyNotes(Path(tmpdir))
        today = date.today()
        daily.write_note("完成了记忆模块", today)

        content = daily.read_note(today)
        assert "完成了记忆模块" in content


def test_daily_list():
    """列出笔记。"""
    from src.SmallShrimp.core.memory.memory_manager import DailyNotes

    with tempfile.TemporaryDirectory() as tmpdir:
        daily = DailyNotes(Path(tmpdir))
        today = date.today()
        daily.write_note("测试笔记", today)

        notes = daily.list_notes()
        assert len(notes) >= 1
        assert notes[0]["date"] == today.strftime("%Y-%m-%d")


# ── MemoryManager (统一接口) ──

def test_memory_manager_remember():
    """MemoryManager.remember 委托给 TopicMemory。"""
    from src.SmallShrimp.core.memory.memory_manager import MemoryManager

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = MemoryManager(Path(tmpdir))
        record = mgr.remember("用户偏好 dark mode")
        assert record["content"] == "用户偏好 dark mode"


def test_memory_manager_recall():
    """MemoryManager.recall 检索记忆。"""
    from src.SmallShrimp.core.memory.memory_manager import MemoryManager

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = MemoryManager(Path(tmpdir))
        mgr.remember("用户偏好 Python")
        mgr.remember("项目名叫 SmallShrimp")

        results = mgr.recall("python")
        assert len(results) == 1


def test_memory_manager_project_update():
    """MemoryManager.project_update 更新项目。"""
    from src.SmallShrimp.core.memory.memory_manager import MemoryManager

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = MemoryManager(Path(tmpdir))
        mgr.project_update("smallshrimp", "status", "已完成")

        project = mgr.projects.load_project("smallshrimp")
        assert project["status"] == "已完成"


def test_memory_manager_today_note():
    """MemoryManager.today_note 写笔记。"""
    from src.SmallShrimp.core.memory.memory_manager import MemoryManager

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = MemoryManager(Path(tmpdir))
        today = date.today()
        mgr.today_note("今日工作记录")

        content = mgr.daily.read_note(today)
        assert "今日工作记录" in content


def test_memory_manager_inject_memories():
    """inject_memories 将记忆注入消息列表。"""
    from src.SmallShrimp.core.memory.memory_manager import MemoryManager
    from src.SmallShrimp.core.message import SystemMessage, HumanMessage

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = MemoryManager(Path(tmpdir))
        mgr.remember("用户偏好 TypeScript")

        messages = [
            SystemMessage(content="你是助手"),
            HumanMessage(content="帮我查一下"),
        ]

        result = mgr.inject_memories(messages, query="TypeScript")
        assert len(result) == 3  # system + memory + human
        assert "TypeScript" in result[1].content


if __name__ == "__main__":
    test_topic_store()
    test_topic_search_by_keyword()
    test_topic_search_by_tag()
    test_topic_search_limit()
    test_topic_update()
    test_topic_update_nonexistent()
    test_topic_delete()
    test_topic_list_all()
    test_project_save_and_load()
    test_project_list()
    test_project_delete()
    test_project_load_nonexistent()
    test_daily_write_and_read()
    test_daily_list()
    test_memory_manager_remember()
    test_memory_manager_recall()
    test_memory_manager_project_update()
    test_memory_manager_today_note()
    test_memory_manager_inject_memories()
    print("\nAll memory tests passed!")
