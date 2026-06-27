"""Knowledge gap detection — find weaknesses in the knowledge graph.

Three types of gaps:
  1. Isolated entities (degree ≤ 1) — lack connections
  2. Sparse communities (cohesion < 0.15) — lack depth
  3. Bridge nodes (connect 3+ clusters) — critical but fragile
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .graph_store import GraphStore


@dataclass
class KnowledgeGap:
    gap_type: str  # "isolated", "sparse", "bridge"
    entity_name: str
    description: str
    severity: float = 0.0  # 0.0 - 1.0


def detect_gaps(graph: "GraphStore", limit: int = 20) -> list[KnowledgeGap]:
    """Detect knowledge gaps in the graph.

    Returns gaps sorted by severity descending.
    """
    gaps: list[KnowledgeGap] = []
    all_entities = graph.get_all_entities(limit=500)

    if not all_entities:
        return gaps

    # 1. Isolated entities (degree ≤ 1)
    for entity in all_entities:
        neighbors = graph.get_neighbors(entity.name, depth=1)
        degree = len(neighbors.entities) - 1  # Exclude self
        if degree <= 1:
            severity = 1.0 - degree * 0.5  # degree 0 = 1.0, degree 1 = 0.5
            gaps.append(KnowledgeGap(
                gap_type="isolated",
                entity_name=entity.name,
                description=f"实体 '{entity.name}' ({entity.type}) 缺乏连接 (度={degree})",
                severity=severity,
            ))

    # 2. Sparse communities — find connected components and check cohesion
    adj: dict[str, set[str]] = {}
    for entity in all_entities:
        neighbors = graph.get_neighbors(entity.name, depth=1)
        adj[entity.name] = {e.name for e in neighbors.entities if e.name != entity.name}

    visited: set[str] = set()
    communities: list[set[str]] = []

    for entity in all_entities:
        if entity.name in visited:
            continue
        # BFS to find component
        component: set[str] = set()
        queue = [entity.name]
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            component.add(node)
            for neighbor in adj.get(node, set()):
                if neighbor not in visited:
                    queue.append(neighbor)
        if len(component) >= 2:
            communities.append(component)

    for community in communities:
        if len(community) < 3:
            continue
        # Cohesion = actual edges / possible edges
        internal_edges = 0
        for node in community:
            internal_edges += len(adj.get(node, set()) & community)
        internal_edges //= 2  # Undirected
        possible = len(community) * (len(community) - 1) // 2
        cohesion = internal_edges / possible if possible > 0 else 0.0

        if cohesion < 0.15:
            # Find the most connected node in this sparse community as the gap indicator
            hub = max(community, key=lambda n: len(adj.get(n, set())))
            gaps.append(KnowledgeGap(
                gap_type="sparse",
                entity_name=hub,
                description=f"社区 '{hub}' 等 {len(community)} 个实体内聚力低 ({cohesion:.2f})",
                severity=0.6 * (1.0 - cohesion),
            ))

    # 3. Bridge nodes — connect 3+ distinct clusters
    for entity in all_entities:
        neighbors = adj.get(entity.name, set())
        if len(neighbors) < 3:
            continue

        # Check if neighbors form multiple disconnected groups
        neighbor_list = list(neighbors)
        groups = _find_groups(neighbor_list, adj)
        if len(groups) >= 3:
            gaps.append(KnowledgeGap(
                gap_type="bridge",
                entity_name=entity.name,
                description=f"桥接节点 '{entity.name}' 连接 {len(groups)} 个聚类，是关键但薄弱的连接点",
                severity=0.7,
            ))

    # Sort by severity
    gaps.sort(key=lambda g: g.severity, reverse=True)
    return gaps[:limit]


def _find_groups(nodes: list[str], adj: dict[str, set[str]]) -> list[set[str]]:
    """Find disconnected groups among a set of nodes."""
    visited: set[str] = set()
    groups: list[set[str]] = []

    for node in nodes:
        if node in visited:
            continue
        group: set[str] = set()
        queue = [node]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            group.add(current)
            for neighbor in adj.get(current, set()):
                if neighbor in set(nodes) and neighbor not in visited:
                    queue.append(neighbor)
        if group:
            groups.append(group)

    return groups


def render_gap_report(gaps: list[KnowledgeGap]) -> str:
    """Render gaps as a human-readable report."""
    if not gaps:
        return "知识图谱无明显差距。"

    lines = ["## 知识差距报告\n"]
    for gap in gaps:
        icon = {"isolated": "🔗", "sparse": "🕸️", "bridge": "🌉"}.get(gap.gap_type, "❓")
        lines.append(f"- {icon} [{gap.gap_type}] {gap.description} (严重度: {gap.severity:.2f})")

    return "\n".join(lines)
