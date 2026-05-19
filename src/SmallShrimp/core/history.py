"""会话历史管理。"""
import json
from pathlib import Path
from datetime import datetime
from ..core.message import Message

class HistoryManager:
    """管理会话历史的持久化。"""
    def __init__(self, sessions_dir: Path) -> None:
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def save(self, session_id: str, messages: list[Message]) -> None:
        """保存会话历史。"""
        file_path = self.sessions_dir / f"{session_id}.json"
        data = {
            "session_id": session_id,
            "messages": [msg.to_dict() for msg in messages],
            "updated_at": datetime.now().isoformat(),
        }
        file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def load(self, session_id: str) -> list[Message]:
        """加载会话历史。"""
        from ..core.message import HumanMessage, AssistantMessage, ToolMessage
        file_path = self.sessions_dir / f"{session_id}.json"
        if not file_path.exists():
            return []
        data = json.loads(file_path.read_text())
        messages = []
        for msg_data in data.get("messages", []):
            role = msg_data.get("role")
            if role == "user":
                messages.append(HumanMessage(content=msg_data.get("content", "")))
            elif role == "assistant":
                content = msg_data.get("content", "")
                tool_calls = msg_data.get("tool_calls")
                reasoning_content = msg_data.get("reasoning_content")
                msg = AssistantMessage(content=content)
                if tool_calls:
                    msg.tool_calls = tool_calls
                if reasoning_content:
                    msg.reasoning_content = reasoning_content
                messages.append(msg)
            elif role == "tool":
                messages.append(ToolMessage(
                    content=msg_data.get("content", ""),
                    tool_call_id=msg_data.get("tool_call_id", ""),
                    name=msg_data.get("name", ""),
                ))
        return messages

    def list_sessions(self) -> list[dict]:
        """列出所有会话。"""
        sessions = []
        for f in self.sessions_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                sessions.append({
                    "session_id": data.get("session_id", f.stem),
                    "message_count": len(data.get("messages", [])),
                    "updated_at": data.get("updated_at", ""),
                })
            except Exception:
                pass
        return sorted(sessions, key=lambda x: x["updated_at"], reverse=True)

    def delete(self, session_id: str) -> None:
        """删除会话。"""
        file_path = self.sessions_dir / f"{session_id}.json"
        if file_path.exists():
            file_path.unlink()

    def append(self, session_id: str, message: dict) -> None:
        """追加单条消息到会话。"""
        file_path = self.sessions_dir / f"{session_id}.json"
        if not file_path.exists():
            # 创建新会话文件
            data = {
                "session_id": session_id,
                "messages": [message],
                "updated_at": datetime.now().isoformat(),
            }
            file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            # 追加到现有会话
            data = json.loads(file_path.read_text())
            data["messages"].append(message)
            data["updated_at"] = datetime.now().isoformat()
            file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def create_session(self, session_id: str, source: str) -> None:
        """创建新会话（如果不存在）。"""
        file_path = self.sessions_dir / f"{session_id}.json"
        if not file_path.exists():
            data = {
                "session_id": session_id,
                "messages": [],
                "source": source,
                "updated_at": datetime.now().isoformat(),
            }
            file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def get_session_info(self, session_id: str) -> dict | None:
        """获取会话元信息，不加载完整历史。"""
        file_path = self.sessions_dir / f"{session_id}.json"
        if not file_path.exists():
            return None
        try:
            data = json.loads(file_path.read_text())
            return {
                "session_id": data.get("session_id", session_id),
                "source": data.get("source", ""),
                "message_count": len(data.get("messages", [])),
                "agent_id": data.get("agent_id", "pickle"),
                "updated_at": data.get("updated_at", ""),
            }
        except Exception:
            return None