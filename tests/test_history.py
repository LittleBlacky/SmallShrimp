from __future__ import annotations
"""History 管理器测试。"""
import tempfile
from pathlib import Path
from src.SmallShrimp.core.history import HistoryManager
from src.SmallShrimp.core.message import HumanMessage, AssistantMessage, ToolMessage


def test_history_manager_init():
    """测试历史管理器初始化。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = HistoryManager(Path(tmpdir))
        assert manager.sessions_dir.exists()


def test_history_manager_init_creates_dir():
    """测试初始化时创建目录。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        sessions_dir = Path(tmpdir) / "new_sessions"
        manager = HistoryManager(sessions_dir)
        assert sessions_dir.exists()


def test_save_and_load_messages():
    """测试保存和加载消息。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = HistoryManager(Path(tmpdir))
        session_id = "test-session-001"

        # 保存消息
        messages = [
            HumanMessage(content="Hello"),
            AssistantMessage(content="Hi there!"),
        ]
        manager.save(session_id, messages)

        # 加载消息
        loaded = manager.load(session_id)
        assert len(loaded) == 2
        assert loaded[0].content == "Hello"
        assert loaded[1].content == "Hi there!"


def test_load_nonexistent_session():
    """测试加载不存在的会话。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = HistoryManager(Path(tmpdir))
        messages = manager.load("nonexistent-session")
        assert messages == []


def test_list_sessions():
    """测试列出所有会话。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = HistoryManager(Path(tmpdir))

        # 创建多个会话
        manager.save("sess-001", [HumanMessage(content="msg1")])
        manager.save("sess-002", [HumanMessage(content="msg2")])
        manager.save("sess-003", [HumanMessage(content="msg3")])

        sessions = manager.list_sessions()
        session_ids = {s["session_id"] for s in sessions}

        assert len(sessions) == 3
        assert "sess-001" in session_ids
        assert "sess-002" in session_ids
        assert "sess-003" in session_ids


def test_delete_session():
    """测试删除会话。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = HistoryManager(Path(tmpdir))

        session_id = "delete-test"
        manager.save(session_id, [HumanMessage(content="to delete")])
        assert len(manager.load(session_id)) == 1

        manager.delete(session_id)
        assert manager.load(session_id) == []


def test_messages_persistence():
    """测试消息持久化。"""
    tmpdir_obj = tempfile.TemporaryDirectory()
    try:
        tmpdir = Path(tmpdir_obj.name)
        manager = HistoryManager(tmpdir)
        session_id = "persist-test"

        messages = [
            HumanMessage(content="Test message"),
            AssistantMessage(content="Response"),
            ToolMessage(content="tool result", tool_call_id="call123"),
        ]
        manager.save(session_id, messages)

        # 在新实例中加载
        manager2 = HistoryManager(tmpdir)
        loaded = manager2.load(session_id)
        assert len(loaded) == 3
        assert loaded[0].content == "Test message"
        assert loaded[2].tool_call_id == "call123"
    finally:
        tmpdir_obj.cleanup()


def test_message_roundtrip():
    """测试消息往返序列化。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = HistoryManager(Path(tmpdir))
        session_id = "roundtrip-test"

        messages = [
            HumanMessage(content="Hello"),
            AssistantMessage(content="Hi!", tool_calls=[{"id": "call1", "type": "function"}]),
        ]
        manager.save(session_id, messages)

        loaded = manager.load(session_id)
        assert len(loaded) == 2
        assert loaded[1].tool_calls[0]["id"] == "call1"


if __name__ == "__main__":
    test_history_manager_init()
    test_history_manager_init_creates_dir()
    test_save_and_load_messages()
    test_load_nonexistent_session()
    test_list_sessions()
    test_delete_session()
    test_messages_persistence()
    test_message_roundtrip()
    print("\nAll test_history tests passed!")