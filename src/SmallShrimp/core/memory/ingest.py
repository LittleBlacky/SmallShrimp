"""Two-step CoT ingest pipeline for knowledge documents.

Step 1 — Analysis: LLM reads source text, outputs structured analysis
Step 2 — Generation: LLM generates memory entries (entities, concepts, relations)

Supports incremental caching (SHA256 skip for unchanged documents).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .graph_store import GraphStore


@dataclass
class IngestResult:
    entities_created: int = 0
    relations_created: int = 0
    memory_entries: list[str] = field(default_factory=list)
    analysis: str = ""
    skipped: bool = False


ANALYSIS_PROMPT = """分析以下文档，提取关键信息。

## 输出格式（JSON）
```json
{{
  "key_entities": [
    {{"name": "实体名", "type": "person|organization|concept|technology|...", "description": "简述"}}
  ],
  "key_concepts": ["概念1", "概念2"],
  "connections": [
    {{"from": "实体A", "relation": "related_to|uses|...", "to": "实体B", "evidence": "依据"}}
  ],
  "contradictions": ["与已知信息矛盾之处"],
  "suggestions": ["建议补充的知识"]
}}
```

## 已有知识
{existing_knowledge}

## 源文档
{source_text}

## 输出（纯 JSON，无其他文字）"""


GENERATION_PROMPT = """基于以下分析结果，生成知识记忆条目。

## 分析结果
{analysis}

## 任务
为每个关键实体和概念生成一条简洁的记忆描述，格式为纯文本（每行一条）。

## 规则
1. 每条记忆 ≤ 200 字
2. 包含实体类型标签（如 [技术]、[人物]）
3. 如有 [[wikilink]] 引用其他实体，保留原样
4. 不重复已有记忆

## 已有记忆
{existing_memory}

## 输出（每行一条记忆，无编号）"""


async def ingest_document(
    source_text: str,
    llm_caller: Any,
    graph: "GraphStore" | None = None,
    existing_knowledge: str = "",
    cache_dir: Path | None = None,
) -> IngestResult:
    """Two-step CoT ingest: Analysis → Generation.

    Args:
        source_text: Document to ingest
        llm_caller: Object with async .chat(messages) -> dict
        graph: GraphStore for entity/relation creation
        existing_knowledge: Summary of existing knowledge (for context)
        cache_dir: Directory for SHA256 cache (skip unchanged docs)
    """
    if not source_text or not source_text.strip():
        return IngestResult()

    # SHA256 cache check
    text_hash = hashlib.sha256(source_text.encode()).hexdigest()[:16]
    if cache_dir:
        cache_file = cache_dir / f"ingest_{text_hash}.json"
        if cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                return IngestResult(
                    entities_created=cached.get("entities", 0),
                    relations_created=cached.get("relations", 0),
                    memory_entries=cached.get("entries", []),
                    analysis=cached.get("analysis", ""),
                    skipped=True,
                )
            except Exception:
                pass

    result = IngestResult()

    # Step 1: Analysis
    analysis_prompt = ANALYSIS_PROMPT.format(
        existing_knowledge=existing_knowledge[:1000],
        source_text=source_text[:4000],
    )

    try:
        resp = await llm_caller.chat([{"role": "user", "content": analysis_prompt}])
        analysis_raw = resp.get("content", "")
    except Exception:
        return result

    result.analysis = analysis_raw

    # Step 2: Generation
    generation_prompt = GENERATION_PROMPT.format(
        analysis=analysis_raw[:2000],
        existing_memory=existing_knowledge[:1000],
    )

    try:
        resp = await llm_caller.chat([{"role": "user", "content": generation_prompt}])
        entries_raw = resp.get("content", "")
    except Exception:
        return result

    # Parse entries
    entries = [line.strip() for line in entries_raw.split("\n") if line.strip() and not line.startswith("#")]
    result.memory_entries = entries

    # Parse analysis and create graph entities/relations
    if graph:
        entities_count, relations_count = _apply_analysis_to_graph(analysis_raw, graph)
        result.entities_created = entities_count
        result.relations_created = relations_count

    # Cache result
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"ingest_{text_hash}.json"
        try:
            cache_file.write_text(json.dumps({
                "entities": result.entities_created,
                "relations": result.relations_created,
                "entries": result.memory_entries,
                "analysis": result.analysis,
                "timestamp": time.time(),
            }, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    return result


def _apply_analysis_to_graph(
    analysis_raw: str,
    graph: "GraphStore",
) -> tuple[int, int]:
    """Parse LLM analysis and apply entities/relations to graph."""
    from .ontology import normalize_entity_type, normalize_predicate

    json_match = re.search(r'\{.*\}', analysis_raw, re.DOTALL)
    if not json_match:
        return 0, 0

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        return 0, 0

    entities_count = 0
    relations_count = 0

    # Create entities
    for item in data.get("key_entities", []):
        if not isinstance(item, dict):
            continue
        name = item.get("name", "").strip()
        if not name:
            continue
        etype = normalize_entity_type(item.get("type", "other"))
        desc = item.get("description", "")
        graph.upsert_entity(name, etype, desc)
        entities_count += 1

    # Create relations
    for item in data.get("connections", []):
        if not isinstance(item, dict):
            continue
        src = item.get("from", "").strip()
        tgt = item.get("to", "").strip()
        if not src or not tgt:
            continue
        pred = normalize_predicate(item.get("relation", "related_to"))
        # Ensure entities exist
        if graph.get_entity(src) is None:
            graph.upsert_entity(src, "other")
        if graph.get_entity(tgt) is None:
            graph.upsert_entity(tgt, "other")
        graph.add_relation(src, pred, tgt, source_text=item.get("evidence", "")[:200])
        relations_count += 1

    return entities_count, relations_count
