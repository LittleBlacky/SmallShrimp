from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

from .message import HumanMessage, Message, SystemMessage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ForkOptions:
    """Options for forking a session into an independent child context."""

    task: str = ""
    max_messages: int = 12
    max_chars: int = 12000
    agent_id: str | None = None


@dataclass(frozen=True)
class ForkedSession:
    """Metadata and copied context for a forked session."""

    session_id: str
    parent_session_id: str
    agent_id: str
    messages: list[Message]
    task: str = ""


def fork_session(parent_session, options: ForkOptions | None = None) -> ForkedSession:
    """Fork recent parent context into a new independent session snapshot."""
    options = options or ForkOptions()
    parent_state = parent_session.state
    parent_agent = parent_session.agent
    agent_def = parent_agent.agent_def
    agent_id = options.agent_id or getattr(agent_def, "id", None) or getattr(agent_def, "name", "")
    session_id = str(uuid.uuid4())

    messages = list(parent_state.messages or [])[-options.max_messages:]
    copied = _fit_messages(messages, options.max_chars)
    if options.task:
        copied.append(SystemMessage(content=f"Fork task: {options.task}"))

    forked = ForkedSession(
        session_id=session_id,
        parent_session_id=parent_state.session_id,
        agent_id=agent_id,
        messages=copied,
        task=options.task,
    )
    _persist_fork(parent_agent, forked)
    _emit_fork_created(parent_session, forked)
    return forked


async def _run_fork_created_hook(parent_session, forked: ForkedSession) -> None:
    from ..hooks import HookContext, HookPoint

    hooks = getattr(parent_session, "hooks", None)
    if hooks is None:
        return

    await hooks.run(HookContext(
        hook_point=HookPoint.FORK_CREATED,
        session_id=forked.session_id,
        parent_session_id=forked.parent_session_id,
        agent_id=forked.agent_id,
        state=parent_session.state,
        metadata={"task": forked.task},
    ))


def _emit_fork_created(parent_session, forked: ForkedSession) -> None:
    hooks = getattr(parent_session, "hooks", None)
    if hooks is None:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(_run_fork_created_hook(parent_session, forked))
        except Exception:
            logger.exception("Fork created hook dispatch failed")
        return

    async def runner() -> None:
        try:
            await _run_fork_created_hook(parent_session, forked)
        except Exception:
            logger.exception("Fork created hook dispatch failed")

    loop.create_task(runner())


def _fit_messages(messages: list[Message], max_chars: int) -> list[Message]:
    if max_chars <= 0:
        return []

    selected: list[Message] = []
    remaining = max_chars
    for message in reversed(messages):
        content = getattr(message, "content", "") or ""
        size = len(content)
        if size > remaining:
            if remaining > 200:
                selected.append(_copy_message_with_content(message, content[-remaining:]))
            break
        selected.append(message)
        remaining -= size
    selected.reverse()
    return selected


def _copy_message_with_content(message: Message, content: str) -> Message:
    if isinstance(message, HumanMessage):
        return HumanMessage(content=content)
    return SystemMessage(content=content)


def _persist_fork(agent, forked: ForkedSession) -> None:
    history_manager = getattr(agent, "history_manager", None)
    if history_manager is None:
        return

    source = f"fork:{forked.parent_session_id}"
    history_manager.create_session(forked.session_id, source, agent_id=forked.agent_id)
    for message in forked.messages:
        history_manager.append(forked.session_id, message.to_dict())
