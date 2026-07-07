"""Skill 加载器。"""

from __future__ import annotations

from pathlib import Path

from .skill_def import SkillDef


class SkillLoader:
    """加载和管理 Skill 定义。"""

    def __init__(self, skills_dir: Path = Path("workspace/skills")) -> None:
        self.skills_dir = skills_dir

    def discover_skills(self, include_archived: bool = False) -> list[SkillDef]:
        """发现所有 Skill。"""
        if not self.skills_dir.exists():
            return []
        skills: list[SkillDef] = []
        for skill_dir in sorted(self.skills_dir.iterdir(), key=lambda path: path.name):
            if not skill_dir.is_dir():
                continue
            try:
                skill = self._load_from_dir(skill_dir)
            except FileNotFoundError:
                continue
            if skill.status == "archived" and not include_archived:
                continue
            skills.append(skill)
        return skills

    def load(self, name: str) -> SkillDef:
        """根据名称加载 Skill。"""
        skill_dir = self.skills_dir / name
        if skill_dir.exists():
            return self._load_from_dir(skill_dir)

        for candidate in self.discover_skills(include_archived=True):
            if candidate.id == name or candidate.name == name:
                return candidate

        raise FileNotFoundError(f"Skill not found: {name}")

    def list_skills(self) -> list[str]:
        """列出所有 Skill 名称。"""
        if not self.skills_dir.exists():
            return []
        return [skill.id or skill.name for skill in self.discover_skills()]

    def _load_from_dir(self, skill_dir: Path) -> SkillDef:
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            raise FileNotFoundError(f"Skill file not found: {skill_file}")

        skill = SkillDef.from_file(skill_file)
        if not skill.id:
            skill.id = skill_dir.name

        if skill.version:
            version_file = skill_dir / "versions" / skill.version / "SKILL.md"
            if version_file.exists():
                skill.content = version_file.read_text(encoding="utf-8").strip()

        return skill
