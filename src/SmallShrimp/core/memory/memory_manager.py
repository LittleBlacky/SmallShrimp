from __future__ import annotations
"""Layered memory manager for persistent profile, facts, reflections, and sessions."""
import json
import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from datetime import datetime, date
from typing import Iterable, Literal, TypedDict

from ..message import Message

MemoryLayer = Literal["profile", "facts", "projects", "reflections", "sessions"]

VALID_MEMORY_LAYERS: tuple[MemoryLayer, ...] = (
    "profile",
    "facts",
    "projects",
    "reflections",
    "sessions",
)


class MemoryRecord(TypedDict, total=False):
    """一条分层记忆记录。"""
    id: str
    content: str
    layer: MemoryLayer
    source: str
    importance: int
    confidence: float
    recall_count: int
    last_recalled_at: str
    created_at: str
    updated_at: str
    archived: bool


@dataclass(frozen=True)
class MemoryLayerSpec:
    layer: MemoryLayer
    file_name: str
    default_importance: int


_LAYER_SPECS: dict[MemoryLayer, MemoryLayerSpec] = {
    "profile": MemoryLayerSpec("profile", "profile/user.jsonl", 10),
    "facts": MemoryLayerSpec("facts", "facts/facts.jsonl", 5),
    "projects": MemoryLayerSpec("projects", "projects/projects.jsonl", 6),
    "reflections": MemoryLayerSpec("reflections", "reflections/agent.jsonl", 6),
    "sessions": MemoryLayerSpec("sessions", "sessions/sessions.jsonl", 3),
}


class LayeredMemoryStore:
    """JSONL-backed store for one explicit memory layer."""

    def __init__(self, root_dir: Path, layer: MemoryLayer, max_entries: int = 2000):
        self.root_dir = root_dir
        self.layer = layer
        self.spec = _LAYER_SPECS[layer]
        self.file_path = root_dir / self.spec.file_name
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_entries = max_entries

    def _load_all(self) -> list[MemoryRecord]:
        if not self.file_path.exists():
            return []
        records: list[MemoryRecord] = []
        with open(self.file_path, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                record = _normalize_record(json.loads(line), self.layer, self.spec.default_importance)
                if not record.get("archived"):
                    records.append(record)
        return records

    def _save_all(self, records: list[MemoryRecord]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.file_path, "w", encoding="utf-8") as file:
            for record in records:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def store(self, content: str, *, source: str = "auto", importance: int | None = None,
              confidence: float = 1.0, dedup_threshold: float = 7.0) -> MemoryRecord:
        content = content.strip()
        if not content:
            raise ValueError("memory content must be non-empty")

        records = self._load_all()
        now = datetime.now().isoformat()
        importance = self.spec.default_importance if importance is None else _clamp_int(importance, 0, 10)
        confidence = _clamp_float(confidence, 0.0, 1.0)

        for existing in records:
            if _is_duplicate_memory(content, existing.get("content", ""), dedup_threshold):
                existing["content"] = content
                existing["source"] = source
                existing["importance"] = max(existing.get("importance", 0), importance)
                existing["confidence"] = confidence
                existing["updated_at"] = now
                self._save_all(records)
                return existing

        record: MemoryRecord = {
            "id": _new_memory_id(),
            "content": content,
            "layer": self.layer,
            "source": source,
            "importance": importance,
            "confidence": confidence,
            "recall_count": 0,
            "created_at": now,
            "updated_at": now,
            "archived": False,
        }
        records.append(record)
        self._evict(records)
        self._save_all(records)
        return record

    def search(self, query: str, limit: int = 10) -> list[MemoryRecord]:
        records = self._load_all()
        scored: list[tuple[float, MemoryRecord]] = []
        for record in records:
            score = _rank_memory(query, record.get("content", ""))
            if score >= 1.0 or not query:
                scored.append((score + _memory_quality_boost(record), record))
        scored.sort(key=lambda item: item[0], reverse=True)
        result = [record for _, record in scored[:limit]]

        if result and query:
            now = datetime.now().isoformat()
            recalled_ids = {record["id"] for record in result}
            for record in records:
                if record.get("id") in recalled_ids:
                    record["recall_count"] = record.get("recall_count", 0) + 1
                    record["last_recalled_at"] = now
            self._save_all(records)
        return result

    def list_all(self) -> list[MemoryRecord]:
        records = self._load_all()
        records.sort(key=lambda record: (record.get("importance", 0), record.get("updated_at", "")), reverse=True)
        return records

    def delete(self, record_id: str) -> bool:
        records = self._load_all()
        kept = [record for record in records if record.get("id") != record_id]
        if len(kept) == len(records):
            return False
        self._save_all(kept)
        return True

    def consolidate(self, threshold: float = 0.8) -> int:
        records = self._load_all()
        records.sort(key=lambda record: (record.get("importance", 0), record.get("recall_count", 0)), reverse=True)
        removed: set[str] = set()
        merged = 0
        for i, left in enumerate(records):
            if left["id"] in removed:
                continue
            for right in records[i + 1:]:
                if right["id"] in removed:
                    continue
                similarity = SequenceMatcher(None, left.get("content", ""), right.get("content", "")).ratio()
                if similarity >= threshold:
                    left["importance"] = max(left.get("importance", 0), right.get("importance", 0))
                    left["recall_count"] = left.get("recall_count", 0) + right.get("recall_count", 0)
                    left["updated_at"] = datetime.now().isoformat()
                    removed.add(right["id"])
                    merged += 1
        if merged:
            self._save_all([record for record in records if record["id"] not in removed])
        return merged

    def _evict(self, records: list[MemoryRecord]) -> None:
        over = len(records) - self.max_entries
        if over <= 0:
            return
        records.sort(key=lambda record: (
            record.get("importance", 0),
            record.get("recall_count", 0),
            record.get("created_at", ""),
        ))
        del records[:over]


class ProjectMemory:
    """项目上下文文件存储，保留现有 key/value API。"""

    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir / "project-state"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def _project_file(self, project_id: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", project_id)
        return self.memory_dir / f"{safe_id}.json"

    def save_project(self, project_id: str, data: dict) -> None:
        file_path = self._project_file(project_id)
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

    def load_project(self, project_id: str) -> dict | None:
        file_path = self._project_file(project_id)
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as file:
            return json.load(file)

    def list_projects(self) -> list[dict]:
        projects = []
        for file_path in self.memory_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as file:
                    projects.append(json.load(file))
            except Exception:
                continue
        return projects


class DailyNotes:
    """每日笔记。"""

    def __init__(self, memory_dir: Path):
        self.daily_dir = memory_dir / "daily-notes"
        self.daily_dir.mkdir(parents=True, exist_ok=True)

    def _note_file(self, note_date: date | None = None) -> Path:
        if note_date is None:
            note_date = date.today()
        return self.daily_dir / f"{note_date.strftime('%Y-%m-%d')}.md"

    def write_note(self, content: str, note_date: date | None = None) -> None:
        file_path = self._note_file(note_date)
        timestamp = datetime.now().strftime("%H:%M:%S")
        with open(file_path, "a", encoding="utf-8") as file:
            file.write(f"\n## [{timestamp}]\n\n{content}\n")

    def read_note(self, note_date: date | None = None) -> str:
        file_path = self._note_file(note_date)
        if not file_path.exists():
            return ""
        return file_path.read_text(encoding="utf-8")

    def list_notes(self, limit: int = 30) -> list[dict]:
        notes = []
        for file_path in sorted(self.daily_dir.glob("*.md"), reverse=True)[:limit]:
            notes.append({"date": file_path.stem, "size": file_path.stat().st_size})
        return notes


class MemoryManager:
    """统一分层记忆管理器。"""

    def __init__(self, memory_dir: Path | None = None):
        if memory_dir is None:
            memory_dir = Path("workspace/memories")
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.stores = {
            layer: LayeredMemoryStore(self.memory_dir, layer)
            for layer in VALID_MEMORY_LAYERS
        }
        self.profile = self.stores["profile"]
        self.facts = self.stores["facts"]
        self.project_memories = self.stores["projects"]
        self.reflections = self.stores["reflections"]
        self.sessions = self.stores["sessions"]
        self.projects = ProjectMemory(self.memory_dir)
        self.daily = DailyNotes(self.memory_dir)

        # ── Per-session frozen snapshot ──
        self._snapshot_profile: list[MemoryRecord] | None = None

    def initialize(self, session_id: str) -> None:
        """初始化会话级缓存快照。

        在 Session 建立时调用，从 SQLite/JSONL 读取 Profile 并缓存到内存。
        本轮内 Correction 写入 SQLite 但不更新此快照，
        新 Profile 从下一轮或新会话开始可见。
        """
        self._snapshot_profile = self.profile.list_all()[:20]

    def system_prompt_block(self) -> str:
        """返回缓存的 Profile 快照，不查库。

        与 get_profile() 不同，此方法只返回 initialize() 时的快照。
        无 profile 条目时返回空字符串，不产生空标题。
        """
        if not self._snapshot_profile:
            return ""
        lines = ["## User Profile\n"]
        for r in self._snapshot_profile:
            lines.append(f"- {r['content']}")
        return "\n".join(lines)

    def refresh_snapshot(self) -> None:
        """重新从 SQLite 加载快照。

        在 on_session_switch / on_session_end 时调用。
        """
        self._snapshot_profile = self.profile.list_all()[:20]

    def remember_profile(self, content: str, *, source: str = "explicit",
                         importance: int = 10, confidence: float = 1.0) -> MemoryRecord:
        return self.profile.store(content, source=source, importance=importance, confidence=confidence)

    def remember_fact(self, content: str, *, source: str = "auto",
                      importance: int = 5, confidence: float = 1.0) -> MemoryRecord:
        return self.facts.store(content, source=source, importance=importance, confidence=confidence)

    def remember_project(self, content: str, *, source: str = "auto",
                         importance: int = 6, confidence: float = 1.0) -> MemoryRecord:
        return self.project_memories.store(content, source=source, importance=importance, confidence=confidence)

    def remember_reflection(self, content: str, *, source: str = "auto",
                            importance: int = 6, confidence: float = 1.0) -> MemoryRecord:
        return self.reflections.store(content, source=source, importance=importance, confidence=confidence)

    def remember_session(self, content: str, *, source: str = "auto",
                         importance: int = 3, confidence: float = 1.0) -> MemoryRecord:
        return self.sessions.store(content, source=source, importance=importance, confidence=confidence)

    def remember(self, content: str, *, layer: str = "facts", source: str = "auto",
                 importance: int | None = None, confidence: float = 1.0) -> MemoryRecord:
        memory_layer = _normalize_layer(layer)
        return self.stores[memory_layer].store(
            content,
            source=source,
            importance=importance,
            confidence=confidence,
        )

    def recall(self, query: str, limit: int = 5,
               layers: Iterable[str] | None = None) -> list[MemoryRecord]:
        search_layers = [_normalize_layer(layer) for layer in layers] if layers else ["facts", "projects", "reflections"]
        scored: list[tuple[float, MemoryRecord]] = []
        for layer in search_layers:
            for record in self.stores[layer].search(query, limit=limit):
                scored.append((_rank_memory(query, record.get("content", "")) + _memory_quality_boost(record), record))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [record for _, record in scored[:limit]]

    def recall_profile(self, query: str = "", limit: int = 10) -> list[MemoryRecord]:
        return self.profile.search(query, limit=limit)

    def get_profile(self, limit: int = 20) -> list[MemoryRecord]:
        return self.profile.list_all()[:limit]

    def list_all(self, layers: Iterable[str] | None = None) -> list[MemoryRecord]:
        selected_layers = [_normalize_layer(layer) for layer in layers] if layers else list(VALID_MEMORY_LAYERS)
        records: list[MemoryRecord] = []
        for layer in selected_layers:
            records.extend(self.stores[layer].list_all())
        records.sort(key=lambda record: (record.get("layer", ""), record.get("updated_at", "")), reverse=True)
        return records

    def delete(self, record_id: str, layers: Iterable[str] | None = None) -> bool:
        selected_layers = [_normalize_layer(layer) for layer in layers] if layers else list(VALID_MEMORY_LAYERS)
        for layer in selected_layers:
            if self.stores[layer].delete(record_id):
                return True
        return False

    def consolidate(self, layers: Iterable[str] | None = None, threshold: float = 0.8) -> int:
        selected_layers = [_normalize_layer(layer) for layer in layers] if layers else ["facts", "projects", "reflections", "sessions"]
        return sum(self.stores[layer].consolidate(threshold=threshold) for layer in selected_layers)

    def project_update(self, project_id: str, key: str, value: object) -> None:
        project = self.projects.load_project(project_id) or {"id": project_id, "name": project_id}
        project[key] = value
        self.projects.save_project(project_id, project)

    def today_note(self, content: str) -> None:
        self.daily.write_note(content)

    def inject_memories(self, messages: list[Message], query: str | None = None, max_records: int = 5) -> list[Message]:
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


# ── Helpers ──────────────────────────────────────────────

def _normalize_layer(layer: str | None) -> MemoryLayer:
    normalized = (layer or "facts").strip().lower().replace("-", "_")
    aliases = {
        "fact": "facts",
        "user_fact": "facts",
        "project": "projects",
        "reflection": "reflections",
        "agent_note": "reflections",
        "session": "sessions",
        "profile": "profile",
        "user_profile": "profile",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in VALID_MEMORY_LAYERS else "facts"


def _normalize_record(record: dict, layer: MemoryLayer, default_importance: int) -> MemoryRecord:
    now = datetime.now().isoformat()
    return {
        "id": str(record.get("id") or _new_memory_id()),
        "content": str(record.get("content", "")),
        "layer": layer,
        "source": str(record.get("source", "auto")),
        "importance": _clamp_int(int(record.get("importance", default_importance)), 0, 10),
        "confidence": _clamp_float(float(record.get("confidence", 1.0)), 0.0, 1.0),
        "recall_count": int(record.get("recall_count", 0)),
        "created_at": str(record.get("created_at", now)),
        "updated_at": str(record.get("updated_at", record.get("created_at", now))),
        "archived": bool(record.get("archived", False)),
        **({"last_recalled_at": str(record["last_recalled_at"])} if record.get("last_recalled_at") else {}),
    }


def _new_memory_id() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S%f")


def _clamp_int(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def _clamp_float(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _memory_quality_boost(record: MemoryRecord) -> float:
    importance = record.get("importance", 0) / 10
    confidence = record.get("confidence", 0.0)
    recall_count = math.log1p(record.get("recall_count", 0)) / 10
    return importance + confidence + recall_count


def _is_duplicate_memory(left: str, right: str, rank_threshold: float = 7.0) -> bool:
    left_clean = left.strip().lower()
    right_clean = right.strip().lower()
    if not left_clean or not right_clean:
        return False
    if left_clean == right_clean:
        return True
    shorter, longer = sorted((left_clean, right_clean), key=len)
    if len(shorter) >= 4 and shorter in longer:
        return True
    if _has_conflicting_number_suffix(left_clean, right_clean):
        return False
    return _rank_memory(left_clean, right_clean) >= rank_threshold and SequenceMatcher(None, left_clean, right_clean).ratio() >= 0.92


def _has_conflicting_number_suffix(left: str, right: str) -> bool:
    left_match = re.search(r"\d+$", left)
    right_match = re.search(r"\d+$", right)
    return bool(left_match and right_match and left_match.group() != right_match.group())


# ── Hybrid Lexical Ranking ───────────────────────────────

def _char_ngrams(text: str, n: int = 2) -> set[str]:
    clean = text.lower().strip()
    return {clean[i:i+n] for i in range(len(clean) - n + 1)}


def _word_terms(text: str) -> set[str]:
    cjk = set(re.findall(r'[\u4e00-\u9fff]', text))
    ascii_words = set(word.lower() for word in re.findall(r'[a-zA-Z]{2,}', text))
    return cjk | ascii_words


def _rank_memory(query: str, content: str) -> float:
    if not query or not content:
        return 0.0

    query_text = query.lower().strip()
    content_text = content.lower().strip()
    score = 0.0

    if query_text in content_text:
        score += 8.0

    query_terms = _word_terms(query_text)
    content_terms = _word_terms(content_text)
    if query_terms:
        score += 4.0 * (len(query_terms & content_terms) / len(query_terms))

    query_grams = _char_ngrams(query_text)
    content_grams = _char_ngrams(content_text)
    if query_grams:
        score += 3.0 * (len(query_grams & content_grams) / len(query_grams))

    ratio = SequenceMatcher(None, query_text, content_text).ratio()
    if ratio >= 0.12:
        score += 2.0 * ratio

    return score
