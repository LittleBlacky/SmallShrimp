"""Built-in agent type presets for sub-agent dispatch.

Three types inspired by Claude Code:
  explore  — read-only tools, fast search
  plan     — read-only + structured planning prompt
  general  — all tools (excluding subagent_dispatch to prevent recursion)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..tools.registry import ToolRegistry


# Tools that are always safe for sub-agents
_READ_ONLY_TOOLS = frozenset({
    "read", "glob", "grep", "websearch", "webread", "tool_search",
    "recall_memory", "search_memory",
})

# Tools excluded from sub-agents to prevent recursion
_SUBAGENT_EXCLUDED = frozenset({
    "subagent_dispatch",
})


@dataclass(frozen=True)
class AgentTypePreset:
    """Defines which tools a sub-agent can access."""
    name: str
    allowed_tools: frozenset[str] | None  # None = all (minus excluded)
    description: str = ""


EXPLORE = AgentTypePreset(
    name="explore",
    allowed_tools=_READ_ONLY_TOOLS,
    description="Read-only search agent. Fast, no side effects.",
)

PLAN = AgentTypePreset(
    name="plan",
    allowed_tools=_READ_ONLY_TOOLS,
    description="Read-only agent with structured planning output.",
)

GENERAL = AgentTypePreset(
    name="general",
    allowed_tools=None,  # all tools, minus subagent_dispatch
    description="Full-capability agent. Excludes sub-agent dispatch to prevent recursion.",
)

AGENT_TYPE_PRESETS: dict[str, AgentTypePreset] = {
    "explore": EXPLORE,
    "plan": PLAN,
    "general": GENERAL,
}


def filter_tools_for_type(
    registry: "ToolRegistry",
    agent_type: str,
) -> "ToolRegistry":
    """Create a filtered ToolRegistry for the given agent type preset."""
    from ..tools.registry import ToolRegistry

    preset = AGENT_TYPE_PRESETS.get(agent_type, GENERAL)
    filtered = ToolRegistry()

    for tool in registry.get_all():
        name = tool.name
        # Always exclude subagent_dispatch in sub-agents
        if name in _SUBAGENT_EXCLUDED:
            continue
        # If preset has an allowed list, filter by it
        if preset.allowed_tools is not None and name not in preset.allowed_tools:
            continue
        filtered.register(tool)

    return filtered
