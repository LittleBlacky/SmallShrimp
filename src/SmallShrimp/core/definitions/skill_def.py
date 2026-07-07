from __future__ import annotations

"""Skill 定义。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class SkillDef:
    """Skill 定义。"""

    id: str
    name: str
    description: str
    content: str = ""
    triggers: list[str] | None = None
    scene: str | None = None
    origin: str = "user"
    status: str = "active"
    created_by: str = "user"
    version: str | None = None
    confidence: float = 1.0
    risk_level: str = "low"
    source_task_id: str | None = None
    pinned: bool = False
    requires_approval: bool = False
    related_skills: list[str] | None = None
    last_used_at: str | None = None
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    user_correction_count: int = 0

    def to_dict(self) -> dict:
        """转换为字典。"""
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "content": self.content,
        }
        optional_values = {
            "triggers": self.triggers,
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
            "related_skills": self.related_skills,
            "last_used_at": self.last_used_at,
            "usage_count": self.usage_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "user_correction_count": self.user_correction_count,
        }
        for key, value in optional_values.items():
            if value not in (None, [], ""):
                data[key] = value
        return data

    @classmethod
    def from_file(cls, path: str | Path) -> "SkillDef":
        path = Path(path)
        content = path.read_text(encoding="utf-8")
        return cls._parse(content)

    @classmethod
    def _parse(cls, content: str) -> "SkillDef":
        if content.startswith("---"):
            parts = content.split("\n---", 1)
            if len(parts) >= 2:
                frontmatter_text = parts[0].replace("---", "").strip()
                frontmatter = yaml.safe_load(frontmatter_text) if frontmatter_text else {}
                body = parts[1].strip()
                return cls.from_parts(frontmatter or {}, body)
        # 无 frontmatter，使用纯内容
        return cls(
            id="",
            name="",
            description="",
            content=content.strip(),
        )

    @classmethod
    def from_parts(cls, metadata: dict[str, Any], content: str) -> "SkillDef":
        return cls(
            id=str(metadata.get("id", "") or ""),
            name=str(metadata.get("name", "") or ""),
            description=str(metadata.get("description", "") or ""),
            content=content,
            triggers=metadata.get("triggers"),
            scene=metadata.get("scene"),
            origin=metadata.get("origin", "user"),
            status=metadata.get("status", "active"),
            created_by=metadata.get("created_by", "user"),
            version=str(metadata["version"]) if metadata.get("version") is not None else None,
            confidence=float(metadata.get("confidence", 1.0)),
            risk_level=metadata.get("risk_level", "low"),
            source_task_id=metadata.get("source_task_id"),
            pinned=bool(metadata.get("pinned", False)),
            requires_approval=bool(metadata.get("requires_approval", False)),
            related_skills=metadata.get("related_skills"),
            last_used_at=metadata.get("last_used_at"),
            usage_count=int(metadata.get("usage_count", 0)),
            success_count=int(metadata.get("success_count", 0)),
            failure_count=int(metadata.get("failure_count", 0)),
            user_correction_count=int(metadata.get("user_correction_count", 0)),
        )
