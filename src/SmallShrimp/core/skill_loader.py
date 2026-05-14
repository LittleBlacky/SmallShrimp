"""Skill 加载器。"""
from pathlib import Path
from ..core.skill_def import SkillDef

class SkillLoader:
    """加载和管理 Skill 定义。"""
    def __init__(self, skills_dir: Path = Path("workspace/skills")) -> None:
        self.skills_dir = skills_dir

    def discover_skills(self) -> list[SkillDef]:
        """发现所有 Skill。"""
        if not self.skills_dir.exists():
            return []
        skills = []
        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                skills.append(SkillDef.from_file(skill_file))
        return skills

    def load(self, name: str) -> SkillDef:
        """根据名称加载 Skill。"""
        skill_path = self.skills_dir / name / "SKILL.md"
        return SkillDef.from_file(skill_path)

    def list_skills(self) -> list[str]:
        """列出所有 Skill 名称。"""
        if not self.skills_dir.exists():
            return []
        return [d.name for d in self.skills_dir.iterdir() if d.is_dir()]