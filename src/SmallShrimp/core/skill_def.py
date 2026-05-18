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
    content: str

    @classmethod
    def from_file(cls, path: str | Path) -> "SkillDef":
        path = Path(path)
        content = path.read_text(encoding="utf-8")
        return cls._parse(content)

    @classmethod
    def _parse(cls, content: str) -> "SkillDef":
        pattern = r"^---\n(.*?)---\n(.*)$"
        match = re.match(pattern, content, re.DOTALL)
        if not match:
            raise ValueError("Invalid SKILL.md format")
        frontmatter = yaml.safe_load(match.group(1))
        return cls(
            id=frontmatter.get("id", ""),
            name=frontmatter.get("name", ""),
            description=frontmatter.get("description", ""),
            content=match.group(2).strip(),
        )