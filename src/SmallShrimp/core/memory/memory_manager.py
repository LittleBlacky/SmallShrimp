from __future__ import annotations
"""Memory Manager - Manages persistent memories across sessions."""
import json
import math
import re
from difflib import SequenceMatcher
from pathlib import Path
from datetime import datetime, date
from typing import TypedDict

from ..message import HumanMessage, AssistantMessage, Message


class MemoryRecord(TypedDict, total=False):
    """记忆记录结构。"""
    id: str
    content: str
    pinned: bool
    recall_count: int
    created_at: str
    updated_at: str


class TopicMemory:
    """主题记忆 - 长期存储的事实和偏好。"""

    def __init__(self, memory_dir: Path, max_entries: int = 100):
        self.file_path = memory_dir / "topics" / "topics.jsonl"
        self.memory_dir = memory_dir / "topics"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.max_entries = max_entries

    def _load_all(self) -> list[MemoryRecord]:
        if not self.file_path.exists():
            return []
        records = []
        with open(self.file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def _save_all(self, records: list[MemoryRecord]) -> None:
        with open(self.file_path, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def store(self, content: str, pinned: bool = False,
              dedup_threshold: float = 7.0) -> MemoryRecord:
        """存储记忆，自动去重：如果与已有记忆高度相似则更新而非新增。"""
        records = self._load_all()

        # 去重：用 _rank_memory 检测相似度
        for existing in records:
            score = _rank_memory(content, existing.get("content", ""))
            if score >= dedup_threshold:
                existing["content"] = content
                existing["updated_at"] = datetime.now().isoformat()
                self._save_all(records)
                return existing

        record: MemoryRecord = {
            "id": datetime.now().strftime("%Y%m%d%H%M%S"),
            "content": content,
            "pinned": pinned,
            "recall_count": 0,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        records.append(record)
        self._evict(records)
        self._save_all(records)
        return record

    def search(self, query: str, limit: int = 10) -> list[MemoryRecord]:
        """混合词法评分搜索，命中记录自动累加 recall_count。"""
        records = self._load_all()
        scored: list[tuple[float, MemoryRecord]] = []
        for r in records:
            score = _rank_memory(query, r.get("content", ""))
            if score > 0 or not query:
                scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        result = [r for _, r in scored[:limit]]

        # 命中计次：更新 recall_count 并回写
        if result and query:
            for r in result:
                r["recall_count"] = r.get("recall_count", 0) + 1
            self._save_all(records)

        return result

    def update(self, record_id: str, content: str | None = None, pinned: bool | None = None) -> MemoryRecord | None:
        """更新记忆。"""
        records = self._load_all()
        for record in records:
            if record["id"] == record_id:
                if content is not None:
                    record["content"] = content
                if pinned is not None:
                    record["pinned"] = pinned
                record["updated_at"] = datetime.now().isoformat()
                self._save_all(records)
                return record
        return None

    def delete(self, record_id: str) -> bool:
        """删除记忆。"""
        records = self._load_all()
        original_len = len(records)
        records = [r for r in records if r["id"] != record_id]
        if len(records) < original_len:
            self._save_all(records)
            return True
        return False

    def list_all(self) -> list[MemoryRecord]:
        """列出所有记忆。"""
        return self._load_all()

    def _evict(self, records: list[MemoryRecord]) -> None:
        """超出容量时淘汰 recall_count 最低的非 pinned 记录。"""
        over = len(records) - self.max_entries
        if over <= 0:
            return
        # 按 recall_count 升序、created_at 升序（越旧越先淘汰）
        records.sort(key=lambda r: (
            r.get("recall_count", 0),
            r.get("created_at", ""),
        ))
        # 跳过 pinned 记录
        to_remove = []
        for r in records:
            if len(to_remove) >= over:
                break
            if not r.get("pinned"):
                to_remove.append(r)
        for r in to_remove:
            records.remove(r)


class ProjectMemory:
    """项目记忆 - 按项目存储上下文。"""

    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir / "projects"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def _project_file(self, project_id: str) -> Path:
        """获取项目文件路径。"""
        safe_id = re.sub(r'[^\w\-.]', '_', project_id)
        return self.memory_dir / f"{safe_id}.json"

    def save_project(self, project_id: str, data: dict) -> None:
        """保存项目数据。"""
        file_path = self._project_file(project_id)
        data["updated_at"] = datetime.now().isoformat()
        file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_project(self, project_id: str) -> dict | None:
        """加载项目数据。"""
        file_path = self._project_file(project_id)
        if not file_path.exists():
            return None
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def list_projects(self) -> list[dict]:
        """列出所有项目。"""
        projects = []
        for f in self.memory_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                projects.append({
                    "id": data.get("id", f.stem),
                    "name": data.get("name", f.stem),
                    "updated_at": data.get("updated_at", ""),
                })
            except Exception:
                projects.append({"id": f.stem, "name": f.stem, "updated_at": ""})
        return sorted(projects, key=lambda p: p["updated_at"], reverse=True)

    def delete_project(self, project_id: str) -> bool:
        """删除项目。"""
        file_path = self._project_file(project_id)
        if file_path.exists():
            file_path.unlink()
            return True
        return False


class DailyNotes:
    """日常笔记 - 按日期记录。"""

    def __init__(self, memory_dir: Path):
        self.daily_dir = memory_dir / "daily-notes"
        self.daily_dir.mkdir(parents=True, exist_ok=True)

    def _note_file(self, note_date: date | None = None) -> Path:
        if note_date is None:
            note_date = date.today()
        return self.daily_dir / f"{note_date.strftime('%Y-%m-%d')}.md"

    def write_note(self, content: str, note_date: date | None = None) -> None:
        """写入笔记（追加模式）。"""
        file_path = self._note_file(note_date)
        timestamp = datetime.now().strftime("%H:%M:%S")
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(f"\n## [{timestamp}]\n\n{content}\n")

    def read_note(self, note_date: date | None = None) -> str:
        """读取笔记。"""
        file_path = self._note_file(note_date)
        if not file_path.exists():
            return ""
        return file_path.read_text(encoding="utf-8")

    def list_notes(self, limit: int = 30) -> list[dict]:
        """列出最近的笔记。"""
        notes = []
        for f in sorted(self.daily_dir.glob("*.md"), reverse=True)[:limit]:
            notes.append({
                "date": f.stem,
                "size": f.stat().st_size,
            })
        return notes


class MemoryManager:
    """统一记忆管理器，整合 Topic、Project、DailyNotes。"""

    def __init__(self, memory_dir: Path | None = None):
        if memory_dir is None:
            memory_dir = Path("workspace/memories")
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        self.topics = TopicMemory(self.memory_dir)
        self.projects = ProjectMemory(self.memory_dir)
        self.daily = DailyNotes(self.memory_dir)

    def recall(self, query: str, limit: int = 5) -> list[MemoryRecord]:
        """从记忆库中检索相关内容。"""
        return self.topics.search(query, limit=limit)

    def remember(self, content: str, pinned: bool = False) -> MemoryRecord:
        """存储新记忆。"""
        return self.topics.store(content, pinned=pinned)

    def project_update(self, project_id: str, key: str, value: any) -> None:
        """更新项目上下文。"""
        project = self.projects.load_project(project_id) or {"id": project_id, "name": project_id}
        project[key] = value
        self.projects.save_project(project_id, project)

    def today_note(self, content: str) -> None:
        """写入今日笔记。"""
        self.daily.write_note(content)

    def get_pinned_memories(self) -> list[MemoryRecord]:
        """获取固定记忆（pinned=True，始终在 system prompt 中可见）。"""
        records = self.topics.list_all()
        return [r for r in records if r.get("pinned")]

    def inject_memories(self, messages: list[Message], query: str | None = None, max_records: int = 5) -> list[Message]:
        """将相关记忆注入消息列表前端。"""
        if query:
            records = self.recall(query, limit=max_records)
        else:
            records = self.topics.list_all()[:max_records]

        if not records:
            return messages

        memory_lines = ["## 相关记忆\n"]
        for r in records:
            memory_lines.append(f"- {r['content']}")
        memory_content = "\n".join(memory_lines)

        # 插入到 system message 之后
        from ..message import SystemMessage
        memory_msg = SystemMessage(content=memory_content)
        result = [messages[0], memory_msg] if messages else [memory_msg]
        result.extend(messages[1:] if len(messages) > 1 else [])
        return result


# ── Hybrid Lexical Ranking (aligned with ZLAgent) ──────────

def _char_ngrams(text: str, n: int = 2) -> set[str]:
    """字符 n-gram 集合，用于中英文混合匹配。"""
    clean = text.lower().strip()
    return {clean[i:i+n] for i in range(len(clean) - n + 1)}

def _word_terms(text: str) -> set[str]:
    """单词/词组分词（支持中英文混合）。"""
    # CJK 单字作为 term
    cjk = set(re.findall(r'[\u4e00-\u9fff]', text))
    # ASCII 单词（>=2 字符）
    ascii_words = set(w.lower() for w in re.findall(r'[a-zA-Z]{2,}', text))
    return cjk | ascii_words

def _rank_memory(query: str, content: str) -> float:
    """混合词法评分：子串 + 词重叠 + n-gram + 序列相似度。"""
    if not query or not content:
        return 0.0

    q = query.lower().strip()
    c = content.lower().strip()
    score = 0.0

    # 1. 精确子串匹配（最高权重，等同 ZLAgent 的 +8.0）
    if q in c:
        score += 8.0

    # 2. 词重叠
    q_terms = _word_terms(q)
    c_terms = _word_terms(c)
    if q_terms:
        score += 4.0 * (len(q_terms & c_terms) / len(q_terms))

    # 3. 字符 n-gram
    q_grams = _char_ngrams(q)
    c_grams = _char_ngrams(c)
    if q_grams:
        score += 3.0 * (len(q_grams & c_grams) / len(q_grams))

    # 4. 序列相似度
    ratio = SequenceMatcher(None, q, c).ratio()
    if ratio >= 0.12:
        score += 2.0 * ratio

    return score
