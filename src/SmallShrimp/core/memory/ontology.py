"""Controlled ontology — entity types and predicates for knowledge graph.

Ported from Comet's ontology with Chinese labels for CJK conversation.
LLM output is clamped to these vocabularies via normalize functions.
"""
from __future__ import annotations

# ── Entity Types (13) ─────────────────────────────────────

ENTITY_TYPES: dict[str, str] = {
    "person": "人物",
    "organization": "组织",
    "location": "地点",
    "concept": "概念",
    "event": "事件",
    "document": "文档",
    "project": "项目",
    "tool": "工具",
    "technology": "技术",
    "skill": "技能",
    "preference": "偏好",
    "habit": "习惯",
    "other": "其他",
}

# Aliases → canonical name
_ENTITY_ALIASES: dict[str, str] = {
    "人": "person", "人物": "person", "用户": "person",
    "组织": "organization", "公司": "organization", "团队": "organization",
    "地点": "location", "地方": "location", "城市": "location",
    "概念": "concept", "想法": "concept", "观点": "concept",
    "事件": "event", "活动": "event",
    "文档": "document", "文件": "document", "文章": "document",
    "项目": "project", "工程": "project",
    "工具": "tool", "软件": "tool", "应用": "tool",
    "技术": "technology", "框架": "technology", "语言": "technology",
    "技能": "skill", "能力": "skill",
    "偏好": "preference", "喜好": "preference",
    "习惯": "habit", "惯例": "habit",
}

# ── Predicates (13) ───────────────────────────────────────

PREDICATES: dict[str, str] = {
    "related_to": "相关",
    "part_of": "属于",
    "uses": "使用",
    "created": "创建了",
    "knows": "认识",
    "prefers": "偏好",
    "located_at": "位于",
    "depends_on": "依赖",
    "similar_to": "相似",
    "contradicts": "矛盾",
    "teaches": "教授",
    "owns": "拥有",
    "belongs_to": "归属于",
}

_PREDICATE_ALIASES: dict[str, str] = {
    "相关": "related_to", "有关": "related_to", "联系": "related_to",
    "属于": "part_of", "包含": "part_of", "组成部分": "part_of",
    "使用": "uses", "用": "uses", "利用": "uses",
    "创建": "created", "创建了": "created", "建立": "created",
    "认识": "knows", "知道": "knows", "了解": "knows",
    "偏好": "prefers", "喜欢": "prefers", "倾向于": "prefers",
    "位于": "located_at", "在": "located_at",
    "依赖": "depends_on", "需要": "depends_on",
    "相似": "similar_to", "类似": "similar_to",
    "矛盾": "contradicts", "冲突": "contradicts",
    "教授": "teaches", "教": "teaches",
    "拥有": "owns", "持有": "owns",
    "归属于": "belongs_to", "归": "belongs_to",
}


def normalize_entity_type(raw: str) -> str:
    """Clamp raw LLM output to controlled entity type vocabulary."""
    raw_lower = raw.strip().lower()
    if raw_lower in ENTITY_TYPES:
        return raw_lower
    if raw_lower in _ENTITY_ALIASES:
        return _ENTITY_ALIASES[raw_lower]
    # Fuzzy: check if any key is substring
    for alias, canonical in _ENTITY_ALIASES.items():
        if alias in raw_lower or raw_lower in alias:
            return canonical
    return "other"


def normalize_predicate(raw: str) -> str:
    """Clamp raw LLM output to controlled predicate vocabulary."""
    raw_lower = raw.strip().lower()
    if raw_lower in PREDICATES:
        return raw_lower
    if raw_lower in _PREDICATE_ALIASES:
        return _PREDICATE_ALIASES[raw_lower]
    for alias, canonical in _PREDICATE_ALIASES.items():
        if alias in raw_lower or raw_lower in alias:
            return canonical
    return "related_to"
