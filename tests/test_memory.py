from __future__ import annotations
"""Memory Manager 测试。"""
import tempfile
from pathlib import Path
from src.SmallShrimp.core.memory import MemoryManager


def test_memory_manager_init():
    """测试记忆管理器初始化。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))
        assert manager.memory_dir.exists()
        assert manager.topics.memory_dir.exists()
        assert manager.projects.memory_dir.exists()
        assert manager.daily.daily_dir.exists()


def test_topic_memory_store_and_search():
    """测试主题记忆存储和搜索。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        from src.SmallShrimp.core.memory.memory_manager import TopicMemory
        topics = TopicMemory(Path(tmpdir))

        # 存储记忆
        record1 = topics.store("用户喜欢 Python 编程", pinned=True)
        assert record1["content"] == "用户喜欢 Python 编程"
        assert record1.get("pinned") is True

        record2 = topics.store("项目使用 FastAPI 框架")
        assert record2.get("pinned") is False

        # 搜索
        results = topics.search("Python")
        assert len(results) >= 1

        # 空搜索
        results = topics.search("")
        assert len(results) >= 2


def test_topic_memory_update_and_delete():
    """测试主题记忆更新和删除。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        from src.SmallShrimp.core.memory.memory_manager import TopicMemory
        topics = TopicMemory(Path(tmpdir))

        record = topics.store("原始内容")
        record_id = record["id"]

        # 更新
        updated = topics.update(record_id, content="更新后内容", pinned=True)
        assert updated is not None
        assert updated["content"] == "更新后内容"
        assert updated.get("pinned") is True

        # 删除
        assert topics.delete(record_id) is True
        assert topics.search("", limit=20) == []


def test_project_memory():
    """测试项目记忆。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        from src.SmallShrimp.core.memory.memory_manager import ProjectMemory
        projects = ProjectMemory(Path(tmpdir))

        # 保存项目
        projects.save_project("test-project", {
            "id": "test-project",
            "name": "Test Project",
            "language": "Python",
        })

        # 加载项目
        data = projects.load_project("test-project")
        assert data is not None
        assert data["language"] == "Python"

        # 列出项目
        project_list = projects.list_projects()
        assert len(project_list) >= 1

        # 删除项目
        assert projects.delete_project("test-project") is True
        assert projects.load_project("test-project") is None


def test_daily_notes():
    """测试日常笔记。"""
    import datetime
    with tempfile.TemporaryDirectory() as tmpdir:
        from src.SmallShrimp.core.memory.memory_manager import DailyNotes
        daily = DailyNotes(Path(tmpdir))

        # 写入笔记
        daily.write_note("今天完成了内存模块的开发")

        # 读取笔记
        content = daily.read_note()
        assert "今天完成了内存模块的开发" in content

        # 列出笔记
        notes = daily.list_notes()
        assert len(notes) >= 1


def test_memory_recall():
    """测试统一检索接口。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))

        manager.remember("用户偏好使用 dark mode")

        results = manager.recall("dark mode")
        assert len(results) >= 1
        assert "dark mode" in results[0]["content"]


def test_memory_remember():
    """测试统一存储接口。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))

        record = manager.remember("这是一个重要的事实")
        assert record["content"] == "这是一个重要的事实"


def test_project_update():
    """测试项目上下文更新。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))

        manager.project_update("my-project", "status", "进行中")
        manager.project_update("my-project", "language", "Python")

        data = manager.projects.load_project("my-project")
        assert data["status"] == "进行中"
        assert data["language"] == "Python"


def test_today_note():
    """测试今日笔记。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))

        manager.today_note("测试笔记内容")

        content = manager.daily.read_note()
        assert "测试笔记内容" in content


def test_inject_memories():
    """测试记忆注入消息列表。"""
    from src.SmallShrimp.core.message import SystemMessage, HumanMessage
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(Path(tmpdir))

        # 存储记忆
        manager.remember("用户使用 DeepSeek API")

        # 构建消息列表
        messages = [
            SystemMessage(content="You are an assistant."),
            HumanMessage(content="Hello"),
        ]

        # 注入记忆
        injected = manager.inject_memories(messages, query="DeepSeek")
        assert len(injected) == 3  # system + memory + human
        assert "相关记忆" in injected[1].content


if __name__ == "__main__":
    test_memory_manager_init()
    test_topic_memory_store_and_search()
    test_topic_memory_update_and_delete()
    test_project_memory()
    test_daily_notes()
    test_memory_recall()
    test_memory_remember()
    test_project_update()
    test_today_note()
    test_inject_memories()
    print("\nAll test_memory tests passed!")