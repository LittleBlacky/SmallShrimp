"""Wikilink entity cross-reference — [[entity_name]] syntax.

Parses [[wikilinks]] from text, creates bidirectional relations
in the graph store, and auto-creates missing entities.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .graph_store import GraphStore

# Matches [[entity_name]] with optional display text: [[entity|display]]
WIKILINK_PATTERN = re.compile(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]')


def parse_wikilinks(text: str) -> list[str]:
    """Extract all [[entity_name]] references from text."""
    return WIKILINK_PATTERN.findall(text)


def resolve_wikilinks(
    text: str,
    graph: "GraphStore",
    source_entity: str | None = None,
    auto_create: bool = True,
) -> list[str]:
    """Parse wikilinks and establish relations in the graph.

    Args:
        text: Text containing [[entity_name]] references
        graph: GraphStore instance
        source_entity: The entity this text belongs to (creates relations FROM it)
        auto_create: Create missing entities automatically

    Returns:
        List of resolved entity names
    """
    links = parse_wikilinks(text)
    if not links:
        return []

    resolved = []
    for name in links:
        name = name.strip()
        if not name:
            continue

        # Auto-create entity if missing
        entity = graph.get_entity(name)
        if entity is None and auto_create:
            entity = graph.upsert_entity(name, "other")

        resolved.append(name)

        # Create bidirectional relation if source entity specified
        if source_entity and name != source_entity:
            graph.add_relation(source_entity, "related_to", name, source_text=text[:200])
            graph.add_relation(name, "related_to", source_entity, source_text=text[:200])

    return resolved


def inject_wikilink_relations(
    content: str,
    entity_name: str,
    graph: "GraphStore",
) -> int:
    """Process a memory entry's content for wikilinks and create relations.

    Returns the number of relations created.
    """
    links = parse_wikilinks(content)
    if not links:
        return 0

    count = 0
    for target in links:
        target = target.strip()
        if not target or target == entity_name:
            continue

        # Ensure target entity exists
        if graph.get_entity(target) is None:
            graph.upsert_entity(target, "other")

        # Bidirectional
        graph.add_relation(entity_name, "related_to", target, source_text=content[:200])
        graph.add_relation(target, "related_to", entity_name, source_text=content[:200])
        count += 2

    return count
