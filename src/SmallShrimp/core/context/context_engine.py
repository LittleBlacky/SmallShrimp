"""ContextEngine — abstract interface for pluggable context compression.

Allows swapping the default 4-tier ContextGuard with alternative
strategies (e.g. sliding window, importance-based) via config.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..runtime.session_state import SessionState


class ContextEngine(ABC):
    """Pluggable context compression strategy."""

    @abstractmethod
    async def check_and_compact(self, state: SessionState) -> SessionState:
        """Inspect context size and compact if needed. Returns (possibly modified) state."""

    @abstractmethod
    def estimate_tokens(self, state: SessionState) -> int:
        """Estimate current token count for the session."""

    def on_session_start(self, session_id: str) -> None:
        """Hook called when a new session begins."""

    def on_session_end(self, session_id: str) -> None:
        """Hook called when a session ends."""

    def on_response(self, input_tokens: int, output_tokens: int) -> None:
        """Hook called after each LLM response with actual usage."""


# Registry for alternative engines
_CONTEXT_ENGINES: dict[str, type[ContextEngine]] = {}


def register_context_engine(name: str, cls: type[ContextEngine]) -> None:
    _CONTEXT_ENGINES[name] = cls


def create_context_engine(
    name: str = "default",
    **kwargs,
) -> ContextEngine:
    """Factory — falls back to DefaultContextEngine (the existing ContextGuard)."""
    if name == "default" or name not in _CONTEXT_ENGINES:
        from .context_guard import ContextGuard
        return ContextGuard(**kwargs)
    return _CONTEXT_ENGINES[name](**kwargs)
