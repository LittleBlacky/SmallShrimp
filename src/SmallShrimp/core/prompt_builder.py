"""Prompt builder that assembles system prompt from layers with prefix cache awareness."""
from __future__ import annotations

from typing import TYPE_CHECKING

from pathlib import Path

if TYPE_CHECKING:
    from .events import EventSource
    from .session_state import SessionState


class PromptBuilder:
    """Assembles system prompt from layered sources with 3-segment cache strategy.

    Layers:
    ── Permanent cache (process lifetime, byte-stable) ──
      L1: Identity  – AGENT.md body
      L2: Soul      – SOUL.md (optional)
      L3: Bootstrap – BOOTSTRAP.md + AGENTS.md + cron list
    ── Frozen segment (session lifetime, byte-stable) ──
      L5: User Profile snapshot (from MemoryProvider cache)
    ── Variable segment (per-turn, at tail, doesn't break prefix cache) ──
      L4: Channel hint – platform/cron/agent context
    """

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        # Process-level permanent cache
        self._cached_identity: str | None = None
        self._cached_soul: str | None = None
        self._cached_bootstrap: str | None = None

    # ── Public API ────────────────────────────────────────────────────────

    def build(self, state: "SessionState") -> str:
        """Build the full system prompt from cached layers."""
        agent_def = state.agent.agent_def
        layers: list[str] = []

        # ── L1: Identity (permanent cache) ──
        if self._cached_identity is None:
            agent_md = getattr(agent_def, "agent_md", None)
            if agent_md:
                self._cached_identity = agent_md
            else:
                self._cached_identity = self._build_legacy_identity(agent_def)
        layers.append(self._cached_identity)

        # ── L2: Soul / Personality (permanent cache, optional) ──
        if self._cached_soul is None:
            soul_md = getattr(agent_def, "soul_md", "")
            self._cached_soul = f"## Personality\n\n{soul_md}" if soul_md else ""
        if self._cached_soul:
            layers.append(self._cached_soul)

        # ── L3: Bootstrap context (permanent cache) ──
        if self._cached_bootstrap is None:
            self._cached_bootstrap = self._load_bootstrap_context()
        if self._cached_bootstrap:
            layers.append(self._cached_bootstrap)

        # ── L5: User Profile snapshot (from MemoryProvider cache, no DB) ──
        memory_block = self._build_profile_block(state)
        if memory_block:
            layers.append(memory_block)

        # ── L4: Channel hint (per-turn, at tail, doesn't break prefix cache) ──
        if state.source is not None:
            layers.append(self._build_channel_hint(state.source))

        return "\n\n".join(layers)

    def reload(self) -> None:
        """Clear permanent cache.

        Call when AGENT.md / SOUL.md / BOOTSTRAP.md / AGENTS.md change.
        Cache will be re-populated on next build().
        """
        self._cached_identity = None
        self._cached_soul = None
        self._cached_bootstrap = None

    # ── Private: layer builders ───────────────────────────────────────────

    def _build_legacy_identity(self, agent_def) -> str:
        """Build identity from legacy AgentDef fields (backward compat)."""
        parts = [
            f"You are {agent_def.name}.",
            agent_def.description,
        ]

        if agent_def.guidelines:
            parts.append("\n## Guidelines")
            for g in agent_def.guidelines:
                parts.append(f"- {g}")

        if agent_def.instructions:
            parts.append("\n## Instructions")
            for i in agent_def.instructions:
                parts.append(f"- {i}")

        return "\n".join(parts)

    def _load_bootstrap_context(self) -> str:
        """Load BOOTSTRAP.md + AGENTS.md from workspace (called once, cached)."""
        parts: list[str] = []

        bootstrap_path = self.workspace / "BOOTSTRAP.md"
        if bootstrap_path.exists():
            parts.append(bootstrap_path.read_text(encoding="utf-8").strip())

        agents_path = self.workspace / "AGENTS.md"
        if agents_path.exists():
            parts.append(agents_path.read_text(encoding="utf-8").strip())

        return "\n\n".join(parts)

    def _build_profile_block(self, state: "SessionState") -> str:
        """Get profile snapshot from MemoryProvider cache, no DB query."""
        memory_manager = getattr(state.agent, "memory_manager", None)
        if memory_manager is None:
            return ""
        return memory_manager.system_prompt_block()

    def _build_channel_hint(self, source: "EventSource") -> str:
        """Build platform/channel hint for the agent."""
        if source.is_cron:
            return (
                "You are running as a background cron job. "
                "Your response will not be sent to a user directly."
            )
        if source.is_agent:
            return (
                "You are running as a dispatched subagent. "
                "Your response will be sent to the main agent."
            )
        if source.is_platform:
            return f"You are responding via {source.platform_name}."
        return f"You are responding via {source._namespace}."
