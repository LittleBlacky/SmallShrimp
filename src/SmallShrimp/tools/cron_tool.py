"""Cron tool - 让 Agent 创建和管理定时任务。"""
from pathlib import Path

from ..tools.decorators import tool


def create_cron_tool():
    """创建 cron 管理工具。"""

    @tool(
        name="cron_set",
        description="Create or delete a scheduled cron job. Use 'add' to create, 'delete' to remove by ID.",
    )
    async def cron_set(
        action: str,
        schedule: str = "",
        name: str = "",
        agent: str = "pickle",
        prompt: str = "",
    ) -> str:
        """管理定时任务。action: add | delete"""
        crons_dir = Path("workspace/crons")
        crons_dir.mkdir(parents=True, exist_ok=True)

        if action == "delete":
            cron_path = crons_dir / name.lower().replace(" ", "-")
            if not cron_path.exists():
                return f"定时任务 '{name}' 不存在"
            import shutil
            shutil.rmtree(cron_path)
            return f"已删除定时任务: {name}"

        if action == "add":
            if not schedule or not name:
                return "用法: cron_set action='add' schedule='0 9 * * *' name='morning-report' prompt='发送早报'"
            cron_id = name.lower().replace(" ", "-")
            cron_dir = crons_dir / cron_id
            cron_dir.mkdir(parents=True, exist_ok=True)

            content = f"""---
name: {name}
schedule: "{schedule}"
agent: {agent}
---
{prompt}
"""
            (cron_dir / "CRON.md").write_text(content, encoding="utf-8")
            return f"✓ 已创建定时任务 '{cron_id}': {schedule} → {agent}"

        return f"未知操作: {action}，支持 add / delete"

    return cron_set
