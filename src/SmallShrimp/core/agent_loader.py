from pathlib import Path
from ..utils.def_loader import AgentDef

class AgentLoader:

    def __init__(self, agents_dir: Path) -> None:
        self.agents_dir = agents_dir

    def load(self, name: str) -> AgentDef:
        agent_path = self.agents_dir / name / "AGENT.md"
        agent_def = AgentDef.from_file(agent_path)
        # Load SOUL.md if exists
        agent_def.soul_md = self._load_soul_md(name)
        return agent_def

    def list_agents(self) -> list[str]:
        if not self.agents_dir.exists():
            return []
        return [d.name for d in self.agents_dir.iterdir() if d.is_dir()]

    def discover_agents(self) -> list["AgentDef"]:
        """发现并加载所有 Agent 定义。"""
        result = []
        for name in self.list_agents():
            try:
                result.append(self.load(name))
            except Exception:
                pass
        return result

    def _load_soul_md(self, agent_id: str) -> str:
        """Load SOUL.md file for an agent if it exists."""
        soul_path = self.agents_dir / agent_id / "SOUL.md"
        if soul_path.exists():
            return soul_path.read_text(encoding="utf-8").strip()
        return ""