"""Turn context — one-shot setup for each agent turn.

Extracted from AgentSession.chat() to make the prologue testable
and the orchestrator readable.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .message import HumanMessage, AssistantMessage, SystemMessage

if TYPE_CHECKING:
    from .agent import Agent, AgentSession
    from .session_state import SessionState


@dataclass
class TurnContext:
    """Carries all per-turn setup state into the main loop."""
    turn_id: str
    original_text: str       # user's raw input (for memory sync)
    message: str             # possibly modified (correction hint prepended)
    max_iterations: int
    should_review_memory: bool = False
    memory_intent: str | None = None  # "high" | "medium" | None


async def build_turn_context(
    session: "AgentSession",
    user_message: str,
) -> TurnContext:
    """Run all once-per-turn initialization. Pure setup, no LLM calls."""
    agent = session.agent
    state = session.state

    # 1. MCP lazy init (first chat only)
    if not agent._mcp_registered:
        agent._mcp_registered = True
        from .mcp import register_mcp_tools
        await register_mcp_tools(agent.mcp_manager, agent.tool_registry)

    # 2. Correction detection
    from .correction import detect_correction_combined, render_correction_hint, CorrectionConfidence
    prev_assistant = ""
    for m in reversed(state.messages):
        if isinstance(m, AssistantMessage) and m.content:
            prev_assistant = m.content or ""
            break
    original_text = user_message
    correction = detect_correction_combined(original_text, prev_assistant)
    if correction:
        hint = render_correction_hint(correction)
        user_message = f"{hint}\n\n---\n\n{user_message}"
        if correction.confidence == CorrectionConfidence.HIGH and agent.memory_manager:
            try:
                agent.memory_manager.store("profile", correction.phrase, source="correction")
            except Exception:
                pass

    # 3. Add user message to state
    user_msg = HumanMessage(content=user_message)
    state.add_message(user_msg)

    # 4. Reset guardrails for this turn
    session._guardrail.reset()
    session._turn_failures.clear()

    # 5. Trust dialog (first entry only)
    if not session._trust_checked:
        session._trust_checked = True
        cwd = os.getcwd()
        if not agent.trust_manager.is_trusted(cwd):
            warnings = agent.trust_manager.scan_dangerous(cwd)
            if warnings and (confirm_fn := getattr(session, '_confirm_fn', None)):
                approved = confirm_fn(
                    f"Trust directory '{cwd}'?\nDetected: {', '.join(warnings[:5])}"
                )
                if approved:
                    agent.trust_manager.trust(cwd)

    # 6. Read max_iterations from config
    max_iterations = agent.config.get("max_iterations", 50)

    return TurnContext(
        turn_id=str(uuid.uuid4()),
        original_text=original_text,
        message=user_message,
        max_iterations=max_iterations,
    )
