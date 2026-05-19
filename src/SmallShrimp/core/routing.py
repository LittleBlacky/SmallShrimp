"""Multi-agent routing: matches event sources to agents using regex bindings."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from re import Pattern
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.events import EventSource
    from ..server.context import Context
    from ..utils.config import Config


@dataclass
class Binding:
    """A routing binding that matches sources to agents."""

    agent: str
    value: str
    tier: int = field(init=False)
    pattern: Pattern = field(init=False)

    def __post_init__(self):
        self.pattern = re.compile(f"^{self.value}$")
        self.tier = self._compute_tier()

    def _compute_tier(self) -> int:
        """Compute specificity: 0=exact, 1=specific regex, 2=wildcard."""
        if not any(c in self.value for c in r".*+?[]()|^$"):
            return 0  # Exact match, e.g. "platform-telegram:123"
        if ".*" in self.value:
            return 2  # Wildcard, e.g. "platform-telegram:.*"
        return 1  # Specific regex


@dataclass
class RoutingTable:
    """Routes sources to agents using regex bindings."""

    context: "Context"
    _bindings: list["Binding"] | None = field(default=None, init=False)
    _config_hash: int | None = field(default=None, init=False)

    @property
    def config(self) -> "Config":
        return self.context.config

    def _load_bindings(self) -> list["Binding"]:
        """Load and sort bindings from config. Cached until config changes."""
        bindings_data = self.config.data.get("routing", {}).get("bindings", [])
        current_hash = hash(tuple((b["agent"], b["value"]) for b in bindings_data))

        if self._bindings is not None and self._config_hash == current_hash:
            return self._bindings

        bindings_with_order = [
            (Binding(agent=b["agent"], value=b["value"]), i)
            for i, b in enumerate(bindings_data)
        ]
        bindings_with_order.sort(key=lambda x: (x[0].tier, x[1]))
        self._bindings = [b for b, _ in bindings_with_order]
        self._config_hash = current_hash
        return self._bindings

    def resolve(self, source_str: str) -> str:
        """Return agent_id for source, falling back to default_agent."""
        for binding in self._load_bindings():
            if binding.pattern.match(source_str):
                return binding.agent
        return self.config.default_agent

    def get_or_create_session_id(self, source: "EventSource") -> str:
        """Get existing or create new session_id for source."""
        source_str = str(source)

        # Check cached session
        source_session = self.config.sources.get(source_str)
        if source_session:
            return source_session.session_id

        # Resolve agent and create new session
        agent_id = self.resolve(source_str)
        agent_def = self.context.agent_loader.load(agent_id)
        from ..core.agent import Agent

        agent = Agent(
            agent_def,
            self.context.config,
            self.context.tool_registry,
            self.context.history_manager,
            prompt_builder=self.context.prompt_builder,
        )
        session = agent.new_session(source)
        # 在 history 中记录 agent_id，供 AgentWorker 恢复时使用
        self.context.history_manager.create_session(
            session.session_id, source_str, agent_id=agent_id
        )

        # Cache the session
        from ..utils.config import SourceSessionConfig
        self.config.set_runtime(
            f"sources.{source_str}",
            SourceSessionConfig(session_id=session.session_id),
        )
        return session.session_id

    def persist_binding(self, source_pattern: str, agent_id: str) -> None:
        """Add and persist a routing binding."""
        bindings = self.config.data.get("routing", {}).get("bindings", [])
        bindings.append({"agent": agent_id, "value": source_pattern})
        self.config.set_runtime("routing.bindings", bindings)
        # Invalidate cache
        self._bindings = None
        self._config_hash = None

    def get_bindings(self) -> list["Binding"]:
        """Return current bindings."""
        return self._load_bindings()
