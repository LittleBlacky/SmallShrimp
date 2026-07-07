# Human-in-loop Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first minimal Human-in-loop runtime foundation: structured human requests, in-memory checkpoints, interrupt/resume APIs, and focused tests.

**Architecture:** Add a small `human_loop` runtime module with dataclasses and serialization helpers. Store one pending human request/checkpoint per `SessionState`, then expose `AgentSession.interrupt_for_human()` and `AgentSession.resume_from_human()` without changing the main agent loop or permission system yet.

**Tech Stack:** Python dataclasses, existing `SessionState`, existing `AgentSession`, pytest.

---

## Scope

This plan implements only the minimal runtime substrate. It does not implement automatic fuzzy-demand detection, CLI UI, permission approval migration, persistent checkpoint storage, or multi-endpoint protocols.

## Files

- Create: `src/SmallShrimp/core/runtime/human_loop.py`
- Modify: `src/SmallShrimp/core/runtime/session_state.py`
- Modify: `src/SmallShrimp/core/runtime/agent.py`
- Create: `tests/test_human_loop.py`
- Modify if needed: `src/SmallShrimp/core/runtime/__init__.py`

---

### Task 1: Add Human-in-loop Data Structures

**Files:**
- Create: `src/SmallShrimp/core/runtime/human_loop.py`
- Test: `tests/test_human_loop.py`

- [ ] **Step 1: Write failing dataclass serialization tests**

Add this test file:

```python
from src.SmallShrimp.core.runtime.human_loop import (
    HumanCheckpoint,
    HumanOption,
    HumanRequest,
    HumanResponse,
)


def test_human_request_round_trips_dict():
    request = HumanRequest(
        id="hr_1",
        type="clarification",
        session_id="s1",
        turn_id="t1",
        question="你希望优先整理哪一部分？",
        options=[
            HumanOption(id="structure", label="目录结构", description="先整理目录"),
        ],
        context={"user_message": "帮我整理一下项目"},
        required=True,
        created_at="2026-07-07T10:00:00",
    )

    restored = HumanRequest.from_dict(request.to_dict())

    assert restored == request
    assert restored.options[0].label == "目录结构"


def test_human_response_round_trips_dict():
    response = HumanResponse(
        request_id="hr_1",
        action="answer",
        content="先整理目录结构，不移动文件。",
        selected_option_ids=["structure"],
        edits={"scope": "plan-only"},
        responded_at="2026-07-07T10:01:00",
    )

    restored = HumanResponse.from_dict(response.to_dict())

    assert restored == response
    assert restored.edits["scope"] == "plan-only"


def test_human_checkpoint_round_trips_dict():
    checkpoint = HumanCheckpoint(
        request_id="hr_1",
        session_id="s1",
        turn_id="t1",
        messages_snapshot=[{"role": "user", "content": "帮我整理一下项目"}],
        pending_action={"kind": "clarification"},
        task_summary="用户想整理项目，但范围不清楚。",
        resume_hint="根据用户回答继续。",
        created_at="2026-07-07T10:00:00",
    )

    restored = HumanCheckpoint.from_dict(checkpoint.to_dict())

    assert restored == checkpoint
    assert restored.messages_snapshot[0]["role"] == "user"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_human_loop.py -q
```

Expected: fail because `src.SmallShrimp.core.runtime.human_loop` does not exist.

- [ ] **Step 3: Implement dataclasses and serialization helpers**

Create `src/SmallShrimp/core/runtime/human_loop.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


HumanRequestType = Literal["clarification", "approval", "edit", "feedback"]
HumanResponseAction = Literal["answer", "approve", "reject", "edit", "revise"]


@dataclass
class HumanOption:
    id: str
    label: str
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HumanOption":
        return cls(
            id=str(data.get("id", "")),
            label=str(data.get("label", "")),
            description=str(data.get("description", "")),
        )


@dataclass
class HumanRequest:
    id: str
    type: HumanRequestType
    session_id: str
    turn_id: str | None
    question: str
    options: list[HumanOption] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    required: bool = True
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["options"] = [option.to_dict() for option in self.options]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HumanRequest":
        return cls(
            id=str(data.get("id", "")),
            type=data.get("type", "clarification"),
            session_id=str(data.get("session_id", "")),
            turn_id=data.get("turn_id"),
            question=str(data.get("question", "")),
            options=[
                HumanOption.from_dict(option)
                for option in data.get("options", [])
                if isinstance(option, dict)
            ],
            context=dict(data.get("context", {}) or {}),
            required=bool(data.get("required", True)),
            created_at=str(data.get("created_at", "")),
        )


@dataclass
class HumanResponse:
    request_id: str
    action: HumanResponseAction
    content: str = ""
    selected_option_ids: list[str] = field(default_factory=list)
    edits: dict[str, Any] = field(default_factory=dict)
    responded_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HumanResponse":
        return cls(
            request_id=str(data.get("request_id", "")),
            action=data.get("action", "answer"),
            content=str(data.get("content", "")),
            selected_option_ids=[
                str(item) for item in data.get("selected_option_ids", [])
            ],
            edits=dict(data.get("edits", {}) or {}),
            responded_at=str(data.get("responded_at", "")),
        )


@dataclass
class HumanCheckpoint:
    request_id: str
    session_id: str
    turn_id: str | None
    messages_snapshot: list[dict[str, Any]]
    pending_action: dict[str, Any] = field(default_factory=dict)
    task_summary: str = ""
    resume_hint: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HumanCheckpoint":
        return cls(
            request_id=str(data.get("request_id", "")),
            session_id=str(data.get("session_id", "")),
            turn_id=data.get("turn_id"),
            messages_snapshot=[
                dict(message)
                for message in data.get("messages_snapshot", [])
                if isinstance(message, dict)
            ],
            pending_action=dict(data.get("pending_action", {}) or {}),
            task_summary=str(data.get("task_summary", "")),
            resume_hint=str(data.get("resume_hint", "")),
            created_at=str(data.get("created_at", "")),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_human_loop.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/SmallShrimp/core/runtime/human_loop.py tests/test_human_loop.py
git commit -m "feat: add human loop data structures"
```

---

### Task 2: Store Pending Human Requests in SessionState

**Files:**
- Modify: `src/SmallShrimp/core/runtime/session_state.py`
- Test: `tests/test_human_loop.py`

- [ ] **Step 1: Write failing SessionState tests**

Append to `tests/test_human_loop.py`:

```python
from types import SimpleNamespace

from src.SmallShrimp.core.runtime.session_state import SessionState


def test_session_state_tracks_pending_human_request():
    state = SessionState(session_id="s1", agent=SimpleNamespace())
    request = HumanRequest(
        id="hr_1",
        type="clarification",
        session_id="s1",
        turn_id="t1",
        question="需要澄清吗？",
    )
    checkpoint = HumanCheckpoint(
        request_id="hr_1",
        session_id="s1",
        turn_id="t1",
        messages_snapshot=[],
    )

    state.pending_human_request = request
    state.pending_human_checkpoint = checkpoint
    state.human_trace.append({"event": "human.interrupted", "request_id": "hr_1"})

    assert state.pending_human_request is request
    assert state.pending_human_checkpoint is checkpoint
    assert state.human_trace[0]["event"] == "human.interrupted"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_human_loop.py::test_session_state_tracks_pending_human_request -q
```

Expected: fail because `SessionState` does not define pending human fields.

- [ ] **Step 3: Add pending fields to SessionState**

Modify `src/SmallShrimp/core/runtime/session_state.py`:

```python
if TYPE_CHECKING:
    from .agent import Agent
    from .human_loop import HumanCheckpoint, HumanRequest
    from ..events.events import EventSource
    from ..history import HistoryManager
    from ..context.prompt_builder import PromptBuilder
```

Add fields to `SessionState`:

```python
    pending_human_request: Optional["HumanRequest"] = None
    pending_human_checkpoint: Optional["HumanCheckpoint"] = None
    human_trace: list[dict] = field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_human_loop.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/SmallShrimp/core/runtime/session_state.py tests/test_human_loop.py
git commit -m "feat: track pending human requests in session"
```

---

### Task 3: Add AgentSession Interrupt API

**Files:**
- Modify: `src/SmallShrimp/core/runtime/agent.py`
- Test: `tests/test_human_loop.py`

- [ ] **Step 1: Write failing interrupt tests**

Append to `tests/test_human_loop.py`:

```python
import pytest

from src.SmallShrimp.core.runtime.agent import AgentSession


def make_session():
    agent = SimpleNamespace(agent_def=SimpleNamespace(id="agent", name="agent"))
    state = SessionState(session_id="s1", agent=agent)
    return AgentSession(agent=agent, state=state)


def test_interrupt_for_human_sets_pending_request_and_trace():
    session = make_session()
    request = HumanRequest(
        id="hr_1",
        type="clarification",
        session_id="s1",
        turn_id="t1",
        question="你希望优先整理哪一部分？",
    )
    checkpoint = HumanCheckpoint(
        request_id="hr_1",
        session_id="s1",
        turn_id="t1",
        messages_snapshot=[],
    )

    returned = session.interrupt_for_human(request, checkpoint)

    assert returned is request
    assert session.state.pending_human_request is request
    assert session.state.pending_human_checkpoint is checkpoint
    assert session.state.human_trace[-1]["event"] == "human.interrupted"
    assert session.state.human_trace[-1]["request_id"] == "hr_1"


def test_interrupt_for_human_rejects_second_pending_request():
    session = make_session()
    request = HumanRequest(
        id="hr_1",
        type="clarification",
        session_id="s1",
        turn_id="t1",
        question="第一个问题",
    )
    checkpoint = HumanCheckpoint(
        request_id="hr_1",
        session_id="s1",
        turn_id="t1",
        messages_snapshot=[],
    )
    session.interrupt_for_human(request, checkpoint)

    with pytest.raises(RuntimeError, match="pending human request"):
        session.interrupt_for_human(
            HumanRequest(
                id="hr_2",
                type="clarification",
                session_id="s1",
                turn_id="t2",
                question="第二个问题",
            ),
            HumanCheckpoint(
                request_id="hr_2",
                session_id="s1",
                turn_id="t2",
                messages_snapshot=[],
            ),
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_human_loop.py::test_interrupt_for_human_sets_pending_request_and_trace tests/test_human_loop.py::test_interrupt_for_human_rejects_second_pending_request -q
```

Expected: fail because `AgentSession.interrupt_for_human` does not exist.

- [ ] **Step 3: Implement interrupt API**

Modify `src/SmallShrimp/core/runtime/agent.py`.

Add imports under `TYPE_CHECKING`:

```python
    from .human_loop import HumanCheckpoint, HumanRequest, HumanResponse
```

Add method to `AgentSession`:

```python
    def interrupt_for_human(
        self,
        request: "HumanRequest",
        checkpoint: "HumanCheckpoint",
    ) -> "HumanRequest":
        """Pause the session for a human response."""
        if self.state.pending_human_request is not None:
            raise RuntimeError("session already has a pending human request")
        if request.id != checkpoint.request_id:
            raise ValueError("human request and checkpoint ids do not match")
        if request.session_id != self.session_id:
            raise ValueError("human request session does not match current session")

        self.state.pending_human_request = request
        self.state.pending_human_checkpoint = checkpoint
        self.state.human_trace.append({
            "event": "human.interrupted",
            "request_id": request.id,
            "type": request.type,
            "question": request.question,
            "turn_id": request.turn_id,
        })
        return request
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_human_loop.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/SmallShrimp/core/runtime/agent.py tests/test_human_loop.py
git commit -m "feat: add human interrupt API"
```

---

### Task 4: Add AgentSession Resume API

**Files:**
- Modify: `src/SmallShrimp/core/runtime/agent.py`
- Test: `tests/test_human_loop.py`

- [ ] **Step 1: Write failing resume tests**

Append to `tests/test_human_loop.py`:

```python
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_resume_from_human_injects_response_and_clears_pending():
    session = make_session()
    request = HumanRequest(
        id="hr_1",
        type="clarification",
        session_id="s1",
        turn_id="t1",
        question="你希望优先整理哪一部分？",
    )
    checkpoint = HumanCheckpoint(
        request_id="hr_1",
        session_id="s1",
        turn_id="t1",
        messages_snapshot=[],
        resume_hint="请基于用户澄清继续。",
    )
    session.interrupt_for_human(request, checkpoint)

    with patch.object(session, "chat", new_callable=AsyncMock) as chat:
        chat.return_value = "继续执行完成"
        result = await session.resume_from_human(
            HumanResponse(
                request_id="hr_1",
                action="answer",
                content="先整理目录结构，不移动文件。",
                selected_option_ids=["structure"],
            )
        )

    assert result == "继续执行完成"
    assert session.state.pending_human_request is None
    assert session.state.pending_human_checkpoint is None
    assert session.state.human_trace[-1]["event"] == "human.resumed"
    assert session.state.human_trace[-1]["request_id"] == "hr_1"
    chat.assert_awaited_once()
    resumed_message = chat.await_args.args[0]
    assert "<human_response>" in resumed_message
    assert "先整理目录结构，不移动文件。" in resumed_message


@pytest.mark.asyncio
async def test_resume_from_human_rejects_mismatched_request():
    session = make_session()
    request = HumanRequest(
        id="hr_1",
        type="clarification",
        session_id="s1",
        turn_id="t1",
        question="问题",
    )
    checkpoint = HumanCheckpoint(
        request_id="hr_1",
        session_id="s1",
        turn_id="t1",
        messages_snapshot=[],
    )
    session.interrupt_for_human(request, checkpoint)

    with pytest.raises(ValueError, match="does not match pending human request"):
        await session.resume_from_human(
            HumanResponse(request_id="wrong", action="answer", content="回答")
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_human_loop.py::test_resume_from_human_injects_response_and_clears_pending tests/test_human_loop.py::test_resume_from_human_rejects_mismatched_request -q
```

Expected: fail because `resume_from_human` does not exist.

- [ ] **Step 3: Implement resume API**

Add to `AgentSession`:

```python
    async def resume_from_human(self, response: "HumanResponse") -> str:
        """Resume a paused session with a human response."""
        request = self.state.pending_human_request
        checkpoint = self.state.pending_human_checkpoint
        if request is None or checkpoint is None:
            raise RuntimeError("session has no pending human request")
        if response.request_id != request.id:
            raise ValueError("human response does not match pending human request")

        self.state.pending_human_request = None
        self.state.pending_human_checkpoint = None
        self.state.human_trace.append({
            "event": "human.resumed",
            "request_id": response.request_id,
            "action": response.action,
            "content": response.content,
            "selected_option_ids": list(response.selected_option_ids),
        })
        return await self.chat(self._render_human_response(request, response, checkpoint))

    def _render_human_response(
        self,
        request: "HumanRequest",
        response: "HumanResponse",
        checkpoint: "HumanCheckpoint",
    ) -> str:
        options = ", ".join(response.selected_option_ids)
        return (
            "<human_response>\n"
            f"request_type: {request.type}\n"
            f"question: {request.question}\n"
            f"action: {response.action}\n"
            f"selected_options: {options}\n"
            f"answer: {response.content}\n"
            f"resume_hint: {checkpoint.resume_hint}\n"
            "</human_response>\n\n"
            "请基于用户澄清后的目标继续执行。"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_human_loop.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/SmallShrimp/core/runtime/agent.py tests/test_human_loop.py
git commit -m "feat: resume sessions from human responses"
```

---

### Task 5: Verify Minimal Human-in-loop Foundation

**Files:**
- No new files unless a small import export is needed.

- [ ] **Step 1: Run focused tests**

Run:

```bash
G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_human_loop.py -q
```

Expected: all `test_human_loop.py` tests pass.

- [ ] **Step 2: Run runtime-adjacent tests**

Run:

```bash
G:\Anaconda\envs\smallshrimp\python.exe -m pytest tests/test_runtime_hooks.py tests/test_security_integration.py tests/test_commands.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run compile check**

Run:

```bash
G:\Anaconda\envs\smallshrimp\python.exe -m compileall -q src\SmallShrimp
```

Expected: exit code `0`.

- [ ] **Step 4: Run full suite**

Run:

```bash
G:\Anaconda\envs\smallshrimp\python.exe -m pytest
```

Expected: full suite passes.

- [ ] **Step 5: Final status**

Run:

```bash
git status --short
```

Expected: clean worktree after commits.

---

## Implementation Notes

- Keep `_confirm_fn` unchanged in this batch.
- Do not add fuzzy-demand detection yet.
- Do not change CLI behavior yet.
- Do not persist checkpoints to disk yet.
- Do not add hook events in this batch unless a later review explicitly approves it.
- Keep the first runtime contract small: one session, one pending request, in-memory only.

## Execution Choice

Plan complete and saved to `docs/superpowers/plans/2026-07-07-human-in-loop-runtime.md`. Two execution options:

1. **Subagent-Driven（推荐）**：每个 task 用一个新的子任务上下文执行，任务之间 review，速度快且边界清楚。
2. **Inline Execution**：在当前会话里按 task 顺序执行，每完成一批停下来确认。

建议第一批用 **Inline Execution**，因为改动很小，而且你要求每一步都要商量，不适合并行推进。
