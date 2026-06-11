from __future__ import annotations
"""Layered memory manager for persistent profile, facts, reflections, and sessions.

MemoryManager orchestrates MemoryProviders. 工具层通过 MemoryManager 的公开 API 读写记忆，
不直接调 Provider。
"""
import json
import re
from pathlib import Path
from datetime import date, datetime
from typing import Iterable

from .provider import MemoryProvider
from .builtin.provider import (
    BuiltinProvider,
    _MarkerLayerAdapter,
    MemoryLayer as _MemoryLayer,
    MemoryRecord as _MemoryRecord,
    VALID_MEMORY_LAYERS as _VALID_LAYERS,
)
from .builtin.common import (
    _normalize_layer,
)

# Re-export for backward compat
MemoryLayer = _MemoryLayer
VALID_MEMORY_LAYERS = _VALID_LAYERS
MemoryRecord = _MemoryRecord


class _ProjectMemory:
    """项目上下文文件存储。"""

    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir / "project-state"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def _project_file(self, project_id: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", project_id)
        return self.memory_dir / f"{safe_id}.json"

    def save_project(self, project_id: str, data: dict) -> None:
        with open(self._project_file(project_id), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_project(self, project_id: str) -> dict | None:
        fp = self._project_file(project_id)
        if not fp.exists():
            return None
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_projects(self) -> list[dict]:
        projects = []
        for fp in self.memory_dir.glob("*.json"):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    projects.append(json.load(f))
            except Exception:
                continue
        return projects


class _DailyNotes:
    """每日笔记。"""

    def __init__(self, memory_dir: Path):
        self.daily_dir = memory_dir / "daily-notes"
        self.daily_dir.mkdir(parents=True, exist_ok=True)

    def _note_file(self, note_date: date | None = None) -> Path:
        if note_date is None:
            note_date = date.today()
        return self.daily_dir / f"{note_date.strftime('%Y-%m-%d')}.md"

    def write_note(self, content: str, note_date: date | None = None) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        with open(self._note_file(note_date), "a", encoding="utf-8") as f:
            f.write(f"\n## [{timestamp}]\n\n{content}\n")

    def read_note(self, note_date: date | None = None) -> str:
        fp = self._note_file(note_date)
        if not fp.exists():
            return ""
        return fp.read_text(encoding="utf-8")

    def list_notes(self, limit: int = 30) -> list[dict]:
        notes = []
        for fp in sorted(self.daily_dir.glob("*.md"), reverse=True)[:limit]:
            notes.append({"date": fp.stem, "size": fp.stat().st_size})
        return notes


class MemoryManager:
    """统一分层记忆管理器。

    编排 MemoryProvider，对外提供高层次读写 API。
    工具层通过此类的公开方法操作记忆。
    """

    def __init__(self, memory_dir: Path | None = None):
        if memory_dir is None:
            memory_dir = Path("workspace/memories")
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # 创建内置 JSONL Provider
        self._provider: MemoryProvider = BuiltinProvider(self.memory_dir)

        # 快捷引用（兼容旧代码直接访问 stores/profile/facts 等）
        self.stores = {
            layer: _MarkerLayerAdapter(self._provider._store, layer)
            for layer in _VALID_LAYERS
        }
        self.profile = self.stores["profile"]
        self.facts = self.stores["facts"]
        self.project_memories = self.stores["projects"]
        self.reflections = self.stores["reflections"]
        self.sessions = self.stores["sessions"]

        self.projects = _ProjectMemory(self.memory_dir)
        self.daily = _DailyNotes(self.memory_dir)

    # ── Provider 代理 ───────────────────────────────────

    @property
    def provider(self) -> MemoryProvider:
        """获取当前 Provider（供高级用法）。"""
        return self._provider

    def close(self) -> None:
        """关闭 Provider 后端连接（SQLite 需要）。"""
        self._provider.close()

    def __del__(self) -> None:
        try:
            self._provider.close()
        except Exception:
            pass

    def initialize(self, session_id: str) -> None:
        """初始化会话级缓存快照。

        在 Session 建立时调用，从 JSONL 读取 Profile 并缓存到内存。
        本轮内写入不更新快照，新 Profile 从下一轮或新会话开始可见。
        """
        self._provider.initialize(session_id)

    def system_prompt_block(self) -> str:
        """返回缓存的 Profile 快照，不查库。"""
        return self._provider.system_prompt_block()

    def refresh_snapshot(self) -> None:
        """重新从 JSONL 加载快照（跨会话时调用）。"""
        if isinstance(self._provider, BuiltinProvider):
            self._provider.refresh_snapshot()

    def prefetch(self, query: str, session_id: str = "") -> list[dict]:
        """按需召回记忆，结果注入 user message 尾部。"""
        return self._provider.prefetch(query, session_id=session_id)

    def sync_turn(self, user_content: str, assistant_content: str,
                  session_id: str = "", messages: list | None = None) -> None:
        """持久化本轮对话到 sessions 层。"""
        self._provider.sync_turn(user_content, assistant_content, session_id, messages)

    # ── 读写 API ────────────────────────────────────────

    def remember_profile(self, content: str, *, source: str = "explicit",
                         importance: int = 10, confidence: float = 1.0) -> MemoryRecord:
        return self._provider.store("profile", content, source=source, importance=importance, confidence=confidence)

    def remember_fact(self, content: str, *, source: str = "auto",
                      importance: int = 5, confidence: float = 1.0) -> MemoryRecord:
        return self._provider.store("facts", content, source=source, importance=importance, confidence=confidence)

    def remember_project(self, content: str, *, source: str = "auto",
                         importance: int = 6, confidence: float = 1.0) -> MemoryRecord:
        return self._provider.store("projects", content, source=source, importance=importance, confidence=confidence)

    def remember_reflection(self, content: str, *, source: str = "auto",
                            importance: int = 6, confidence: float = 1.0) -> MemoryRecord:
        return self._provider.store("reflections", content, source=source, importance=importance, confidence=confidence)

    def remember_session(self, content: str, *, source: str = "auto",
                         importance: int = 3, confidence: float = 1.0) -> MemoryRecord:
        return self._provider.store("sessions", content, source=source, importance=importance, confidence=confidence)

    def remember(self, content: str, *, layer: str = "facts", source: str = "auto",
                 importance: int | None = None, confidence: float = 1.0) -> MemoryRecord:
        memory_layer = _normalize_layer(layer)
        return self._provider.store(memory_layer, content, source=source, importance=importance, confidence=confidence)

    def recall(self, query: str, limit: int = 5,
               layers: Iterable[str] | None = None) -> list[MemoryRecord]:
        """搜索任务记忆（facts/projects/reflections），不搜索 profile。"""
        return self._provider.search(query, limit=limit)

    def recall_profile(self, query: str = "", limit: int = 10) -> list[MemoryRecord]:
        return self._provider.search(query, layer="profile", limit=limit)

    def get_profile(self, limit: int = 20) -> list[MemoryRecord]:
        return self._provider.list_all(layer="profile", limit=limit)

    def list_all(self, layers: Iterable[str] | None = None) -> list[MemoryRecord]:
        if layers:
            selected = [_normalize_layer(l) for l in layers]
            records: list[MemoryRecord] = []
            for layer in selected:
                records.extend(self._provider.list_all(layer=layer))
        else:
            records = self._provider.list_all()
        records.sort(key=lambda r: (r.get("layer", ""), r.get("updated_at", "")), reverse=True)
        return records

    def delete(self, record_id: str, layers: Iterable[str] | None = None) -> bool:
        return self._provider.delete(record_id)

    def consolidate(self, layers: Iterable[str] | None = None, threshold: float = 0.8) -> int:
        if isinstance(self._provider, BuiltinProvider):
            return self._provider.consolidate(layers=layers, threshold=threshold)
        return 0

    # ── 项目 / 每日笔记（非记忆层，保持原接口）───────────

    def project_update(self, project_id: str, key: str, value: object) -> None:
        project = self.projects.load_project(project_id) or {"id": project_id, "name": project_id}
        project[key] = value
        self.projects.save_project(project_id, project)

    def today_note(self, content: str) -> None:
        self.daily.write_note(content)

    def inject_memories(self, messages: list, query: str | None = None, max_records: int = 5) -> list:
        """向消息列表注入召回的记忆（兼容旧接口）。"""
        records = self.recall(query or "", limit=max_records)
        if not records:
            return messages

        memory_lines = ["## Relevant Retrieved Memory\n"]
        for record in records:
            memory_lines.append(f"- [{record['layer']}] {record['content']}")
        memory_content = "\n".join(memory_lines)

        from ..message import SystemMessage
        memory_msg = SystemMessage(content=memory_content)
        result = [messages[0], memory_msg] if messages else [memory_msg]
        result.extend(messages[1:] if len(messages) > 1 else [])
        return result


# ── Backward-compat re-exports ─────────────────────────
# 旧版代码从 memory_manager 导入这些类/函数，保持可用
from .builtin.common import (  # noqa: E402, F401
    _rank_memory,
    _memory_quality_boost,
    _normalize_layer,
)
from .builtin.provider import (  # noqa: E402, F401
    _MarkerLayerAdapter as LayeredMemoryStore,
)
ProjectMemory = _ProjectMemory
DailyNotes = _DailyNotes
