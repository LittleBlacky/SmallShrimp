from __future__ import annotations

"""Skill metadata helpers.

SmallShrimp follows the common skill package convention: `name` and
`description` are the only required metadata fields. Product-specific fields
are optional extensions used for evolution, risk, and routing.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

SkillStatus = Literal["draft", "active", "deprecated", "archived"]
SkillRiskLevel = Literal["low", "medium", "high"]
SkillCreatedBy = Literal["agent", "user", "bundled"]
SkillOrigin = Literal["user", "learned", "bundled"]

REQUIRED_METADATA_FIELDS = ("name", "description")


@dataclass
class SkillMetadata:
    name: str
    description: str
    id: str = ""
    triggers: list[str] = field(default_factory=list)
    scene: str | None = None
    origin: SkillOrigin = "user"
    status: SkillStatus = "active"
    created_by: SkillCreatedBy = "user"
    version: str | None = None
    confidence: float = 1.0
    risk_level: SkillRiskLevel = "low"
    source_task_id: str | None = None
    pinned: bool = False
    requires_approval: bool = False
    related_skills: list[str] = field(default_factory=list)
    last_used_at: str | None = None
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    user_correction_count: int = 0

    @classmethod
    def from_yaml_file(cls, path: str | Path) -> "SkillMetadata":
        path = Path(path)
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillMetadata":
        missing = [field_name for field_name in REQUIRED_METADATA_FIELDS if field_name not in data]
        if missing:
            raise ValueError(f"Missing required skill metadata fields: {', '.join(missing)}")

        triggers = data.get("triggers") or []
        if not isinstance(triggers, list):
            raise ValueError("Skill metadata triggers must be a list")

        origin = data.get("origin", "user")
        if origin not in ("user", "learned", "bundled"):
            raise ValueError(f"Invalid skill origin: {origin}")

        status = data.get("status", "active")
        if status not in ("draft", "active", "deprecated", "archived"):
            raise ValueError(f"Invalid skill status: {status}")

        created_by = data.get("created_by", "user")
        if created_by not in ("agent", "user", "bundled"):
            raise ValueError(f"Invalid skill created_by: {created_by}")

        risk_level = data.get("risk_level", "low")
        if risk_level not in ("low", "medium", "high"):
            raise ValueError(f"Invalid skill risk_level: {risk_level}")

        return cls(
            name=str(data["name"]),
            description=str(data["description"]),
            id=str(data.get("id", "") or ""),
            triggers=[str(trigger) for trigger in triggers],
            scene=str(data["scene"]) if data.get("scene") is not None else None,
            origin=origin,
            status=status,
            created_by=created_by,
            version=str(data["version"]) if data.get("version") is not None else None,
            confidence=float(data.get("confidence", 1.0)),
            risk_level=risk_level,
            source_task_id=data.get("source_task_id"),
            pinned=bool(data.get("pinned", False)),
            requires_approval=bool(data.get("requires_approval", False)),
            related_skills=[str(skill) for skill in data.get("related_skills", [])],
            last_used_at=data.get("last_used_at"),
            usage_count=int(data.get("usage_count", 0)),
            success_count=int(data.get("success_count", 0)),
            failure_count=int(data.get("failure_count", 0)),
            user_correction_count=int(data.get("user_correction_count", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "triggers": list(self.triggers),
            "scene": self.scene,
            "origin": self.origin,
            "status": self.status,
            "created_by": self.created_by,
            "version": self.version,
            "confidence": self.confidence,
            "risk_level": self.risk_level,
            "source_task_id": self.source_task_id,
            "pinned": self.pinned,
            "requires_approval": self.requires_approval,
            "related_skills": list(self.related_skills),
            "last_used_at": self.last_used_at,
            "usage_count": self.usage_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "user_correction_count": self.user_correction_count,
        }

    def write_yaml_file(self, path: str | Path) -> None:
        Path(path).write_text(
            yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
