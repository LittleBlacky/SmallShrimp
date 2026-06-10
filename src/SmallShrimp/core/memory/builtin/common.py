"""Shared helper functions for builtin memory providers."""
from __future__ import annotations

import math
import re
import uuid
from datetime import datetime
from difflib import SequenceMatcher
from typing import Literal, TypedDict


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


# ── ID generation ───────────────────────────────────────

def _new_memory_id() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S%f") + uuid.uuid4().hex[:8]


# ── Clamping ────────────────────────────────────────────

def _clamp_int(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def _clamp_float(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


# ── Layer normalization ─────────────────────────────────

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


# ── Normalize record ────────────────────────────────────

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


# ── Query Expansion ─────────────────────────────────────

_QUERY_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "错误": ("失败", "报错", "异常", "error", "bug"),
    "偏好": ("喜欢", "不喜欢", "希望", "习惯", "prefer"),
    "代码": ("编码", "编程", "开发", "写代码", "code"),
    "项目": ("仓库", "repo", "工程", "proj"),
    "配置": ("设置", "config", "setting", "cfg"),
    "路径": ("目录", "文件夹", "folder", "dir"),
    "测试": ("test", "pytest", "unittest", "单元测试"),
}


def _expand_query(query: str) -> set[str]:
    """扩展查询词：命中映射表时返回原始词 + 同义词。"""
    terms = {query}
    for key, expansions in _QUERY_EXPANSIONS.items():
        if key in query:
            terms.update(expansions)
    return terms


# ── Ranking ─────────────────────────────────────────────

def _char_ngrams(text: str, n: int = 2) -> set[str]:
    clean = text.lower().strip()
    return {clean[i:i + n] for i in range(len(clean) - n + 1)}


def _word_terms(text: str) -> set[str]:
    cjk = set(re.findall(r'[\u4e00-\u9fff]', text))
    ascii_words = set(re.findall(r'[a-zA-Z0-9_]+', text.lower()))
    return cjk | ascii_words


def _rank_memory(query: str, content: str) -> float:
    if not query or not content:
        return 0.0
    score = 0.0
    if query.lower() in content.lower():
        score += 8.0
    query_terms = _word_terms(query)
    content_terms = _word_terms(content)
    if query_terms:
        score += 4.0 * (len(query_terms & content_terms) / len(query_terms))
    query_grams = _char_ngrams(query)
    content_grams = _char_ngrams(content)
    if query_grams:
        score += 3.0 * (len(query_grams & content_grams) / len(query_grams))
    ratio = SequenceMatcher(None, query.lower(), content.lower()).ratio()
    if ratio >= 0.12:
        score += 2.0 * ratio
    return score


def _memory_quality_boost(record: MemoryRecord) -> float:
    importance = record.get("importance", 0) / 10
    confidence = record.get("confidence", 0.0)
    recall_count = math.log1p(record.get("recall_count", 0)) / 10
    return importance + confidence + recall_count


# ── Dedup ───────────────────────────────────────────────

def _has_conflicting_number_suffix(left: str, right: str) -> bool:
    left_match = re.search(r"\d+$", left)
    right_match = re.search(r"\d+$", right)
    return bool(left_match and right_match and left_match.group() != right_match.group())


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
