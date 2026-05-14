"""Skill 工具。"""
from ..tools.decorators import tool
from ..core.skill_loader import SkillLoader

def create_skill_tool(skill_loader: SkillLoader):
    """工厂函数：创建 skill 工具。"""
    # 构建 skill 列表描述
    skills = skill_loader.discover_skills()
    skills_xml = "<skills>\n"
    for s in skills:
        skills_xml += f'  <skill name="{s.name}">{s.description}</skill>\n'
    skills_xml += "</skills>"
    
    @tool(
        description=f"Load a skill to get its instructions. {skills_xml}"
    )
    async def skill(skill_name: str) -> str:
        """根据名称加载并返回技能内容。"""
        try:
            skill_def = skill_loader.load(skill_name)
            return skill_def.content
        except FileNotFoundError:
            return f"Skill '{skill_name}' not found. Available skills: {[s.name for s in skill_loader.discover_skills()]}"
        except Exception as e:
            return f"Error loading skill '{skill_name}': {e}"

    return skill