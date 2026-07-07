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
