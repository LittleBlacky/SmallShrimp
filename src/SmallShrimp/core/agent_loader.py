from pathlib import Path
from utils.def_loader import AgentDef

class AgentLoader:

    def __init__(self, agents_dir: Path) -> None:
        self.agents_dir = agents_dir

    def load(self, name: str) -> AgentDef:
        agent_path = self.agents_dir / name / "AGENT.md"
        return AgentDef.from_file(agent_path)

    def list_agents(self) -> list[str]:
        if not self.agents_dir.exists():
            return []
        return [d.name for d in self.agents_dir.iterdir() if d.is_dir()]