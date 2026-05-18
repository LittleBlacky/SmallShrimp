from __future__ import annotations
"""Skill 定义。"""
from dataclasses import dataclass
from pathlib import Path
import yaml
import re

@dataclass
class SkillDef:
    """Skill 定义。"""
    id: str
    name: str
    description: str
    content: str = ""

    def to_dict(self) -> dict:
        """转换为字典。"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "content": self.content,
        }

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
                return cls(
                    id=frontmatter.get("id", "") if frontmatter else "",
                    name=frontmatter.get("name", "") if frontmatter else "",
                    description=frontmatter.get("description", "") if frontmatter else "",
                    content=body,
                )
        # 无 frontmatter，使用纯内容
        return cls(
            id="",
            name="",
            description="",
            content=content.strip(),
        )