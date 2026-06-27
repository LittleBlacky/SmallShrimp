"""Triplet extraction — LLM-based extraction with controlled ontology.

Two-step process:
  1. LLM analyzes text and outputs structured triplets
  2. Output is clamped to controlled vocabulary (ontology.py)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .ontology import normalize_entity_type, normalize_predicate

if TYPE_CHECKING:
    pass  # LLM provider passed as callable


@dataclass
class ExtractedTriplet:
    subject: str
    subject_type: str
    predicate: str
    object: str
    object_type: str
    confidence: float = 0.8
    source_text: str = ""


@dataclass
class TripletExtractionResult:
    triplets: list[ExtractedTriplet] = field(default_factory=list)
    entities: list[dict] = field(default_factory=list)  # [{name, type, description}]
    raw_response: str = ""


EXTRACTION_PROMPT = """从以下文本中提取知识三元组（主体-谓词-客体）。

## 受控词表

实体类型（subject_type/object_type 必须是以下之一）：
person, organization, location, concept, event, document, project, tool, technology, skill, preference, habit, other

谓词（predicate 必须是以下之一）：
related_to, part_of, uses, created, knows, prefers, located_at, depends_on, similar_to, contradicts, teaches, owns, belongs_to

## 输出格式

返回 JSON 数组，每个元素：
```json
{
  "subject": "实体名称",
  "subject_type": "实体类型",
  "predicate": "谓词",
  "object": "客体名称",
  "object_type": "实体类型",
  "confidence": 0.0-1.0
}
```

## 规则
1. 只提取明确陈述的事实，不推断
2. 实体名称用最简短的自然形式
3. 置信度反映文本明确程度
4. 如果没有可提取的三元组，返回空数组 []

## 文本
{text}

## 输出（纯 JSON 数组，无其他文字）"""


async def extract_triplets(
    text: str,
    llm_caller: Any,
) -> TripletExtractionResult:
    """Extract triplets from text using LLM.

    Args:
        text: Source text to extract from
        llm_caller: An object with async .chat(messages) -> dict method
    """
    if not text or not text.strip():
        return TripletExtractionResult()

    prompt = EXTRACTION_PROMPT.format(text=text[:4000])  # Truncate long texts

    try:
        response = await llm_caller.chat([
            {"role": "user", "content": prompt}
        ])
        raw = response.get("content", "")
    except Exception:
        return TripletExtractionResult()

    return _parse_extraction_response(raw, source_text=text)


def _parse_extraction_response(
    raw: str,
    source_text: str = "",
) -> TripletExtractionResult:
    """Parse LLM response into structured triplets, clamping to ontology."""
    result = TripletExtractionResult(raw_response=raw)

    # Extract JSON array from response (may be wrapped in markdown)
    json_match = re.search(r'\[.*\]', raw, re.DOTALL)
    if not json_match:
        return result

    try:
        items = json.loads(json_match.group())
    except json.JSONDecodeError:
        return result

    if not isinstance(items, list):
        return result

    seen_entities: dict[str, dict] = {}

    for item in items:
        if not isinstance(item, dict):
            continue

        subject = str(item.get("subject", "")).strip()
        obj = str(item.get("object", "")).strip()
        if not subject or not obj:
            continue

        # Normalize types and predicate to controlled vocabulary
        subject_type = normalize_entity_type(str(item.get("subject_type", "other")))
        object_type = normalize_entity_type(str(item.get("object_type", "other")))
        predicate = normalize_predicate(str(item.get("predicate", "related_to")))
        confidence = float(item.get("confidence", 0.8))
        confidence = max(0.0, min(1.0, confidence))

        result.triplets.append(ExtractedTriplet(
            subject=subject, subject_type=subject_type,
            predicate=predicate, object=obj, object_type=object_type,
            confidence=confidence, source_text=source_text[:500],
        ))

        # Collect unique entities
        for name, etype in [(subject, subject_type), (obj, object_type)]:
            if name not in seen_entities:
                seen_entities[name] = {"name": name, "type": etype}

    result.entities = list(seen_entities.values())
    return result
