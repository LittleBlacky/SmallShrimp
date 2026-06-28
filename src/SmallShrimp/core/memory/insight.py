"""Insight engine — synthesize high-level knowledge from entity communities.

Inspired by Comet's reflection engine. Takes top entities from each
community, uses LLM to generate a themed insight, stores in reflections.
Deduplicates by community_id (updates existing insight, doesn't stack).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .graph_store import GraphStore
    from .memory_manager import MemoryManager

INSIGHT_PROMPT = """你是一个知识整理专家。请根据以下实体群组，提炼出一个主题洞察。

## 实体群组
{entities_text}

## 关系
{relations_text}

## 要求
1. 用一句话概括这个群组的主题
2. 用 2-3 句话描述关键关系和值得注意的信息
3. 输出格式：[主题] 描述

## 示例
[团队技术栈] 团队主要使用 Python + FastAPI 做后端开发，Alice 和 Bob 是核心成员。FastAPI 依赖 Python，部署使用 Docker。

## 输出（纯文本，无其他文字）"""


async def generate_insight(
    community_id: str,
    graph: "GraphStore",
    llm_caller: Any,
    memory_manager: "MemoryManager | None" = None,
) -> str | None:
    """Generate an insight for a community.

    Args:
        community_id: The community to generate insight for
        graph: GraphStore instance
        llm_caller: Object with async .chat(messages) -> dict
        memory_manager: Optional MemoryManager to store the insight

    Returns:
        The insight text, or None if generation failed.
    """
    members = graph.get_community(community_id)
    if len(members) < 2:
        return None  # Too few members for meaningful insight

    # Build entities text (top 10 by access_count)
    members.sort(key=lambda e: e.access_count, reverse=True)
    top_members = members[:10]

    entities_lines = []
    for e in top_members:
        line = f"- {e.name} ({e.type})"
        if e.description:
            line += f": {e.description}"
        entities_lines.append(line)

    # Build relations text
    relations_lines = []
    seen = set()
    for e in top_members:
        neighbors = graph.get_neighbors(e.name, depth=1)
        for rel in neighbors.relations[:5]:
            src = next((x for x in neighbors.entities if x.id == rel.source_id), None)
            tgt = next((x for x in neighbors.entities if x.id == rel.target_id), None)
            if src and tgt:
                key = f"{src.name}->{rel.predicate}->{tgt.name}"
                if key not in seen:
                    seen.add(key)
                    relations_lines.append(f"- {src.name} → [{rel.predicate}] → {tgt.name}")

    if not entities_lines:
        return None

    prompt = INSIGHT_PROMPT.format(
        entities_text="\n".join(entities_lines),
        relations_text="\n".join(relations_lines[:15]) if relations_lines else "无",
    )

    try:
        response = await llm_caller.chat([{"role": "user", "content": prompt}])
        insight_text = response.get("content", "").strip()
    except Exception:
        return None

    if not insight_text or len(insight_text) < 10:
        return None

    # Store insight in reflections (dedup by community_id)
    if memory_manager:
        # Tag with community_id for dedup
        tagged_content = f"[社区:{community_id}] {insight_text}"
        try:
            memory_manager.store(
                "reflections", tagged_content,
                importance=8, source="insight_engine",
                community_id=community_id,
            )
        except Exception:
            pass

    return insight_text


async def run_insight_cycle(
    graph: "GraphStore",
    llm_caller: Any,
    memory_manager: "MemoryManager | None" = None,
    min_community_size: int = 3,
    max_communities: int = 5,
) -> list[str]:
    """Run one insight generation cycle across all communities.

    Picks the largest communities that don't have recent insights,
    generates insights for each.

    Returns list of generated insight texts.
    """
    communities = graph.list_communities()
    if not communities:
        return []

    # Filter by minimum size and sort by total access
    qualified = [c for c in communities if c["count"] >= min_community_size]
    qualified.sort(key=lambda c: c["total_access"], reverse=True)

    results = []
    for comm in qualified[:max_communities]:
        insight = await generate_insight(
            comm["community_id"], graph, llm_caller, memory_manager,
        )
        if insight:
            results.append(insight)

    return results
