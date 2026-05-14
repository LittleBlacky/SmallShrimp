import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml

@dataclass
class AgentDef:
    name: str
    description: str
    llm: dict[str, Any]
    capabilities: list[str]
    guidelines: list[str]
    instructions: list[str]

    @classmethod
    def from_file(cls, path: str | Path) -> "AgentDef":
        path = Path(path)
        content = path.read_text(encoding="utf-8")
        return cls._parse(content)

    @classmethod
    def _parse(cls, content: str) -> "AgentDef":
        pattern = r"^---\n(.*?)---\n(.*)$"
        match = re.match(pattern, content, re.DOTALL)
        if not match:
            raise ValueError("Invalid AGENT.md format")
    
        frontmatter = yaml.safe_load(match.group(1))
        body = match.group(2)
    
        guidelines = []
        instructions = []
        current_section = None
    
        for line in body.split("\n"):
            if line.startswith("## "):
                current_section = line[3:].strip().lower()
            elif current_section == "guidelines":
                if line.startswith("- "):
                    guidelines.append(line[2:])
            elif current_section == "instructions":
                if line.startswith("- "):
                    instructions.append(line[2:])
    
        return cls(
            name=frontmatter.get("name", ""),
            description=frontmatter.get("description", ""),
            llm=frontmatter.get("llm", {}),
            capabilities=frontmatter.get("capabilities", []),
            guidelines=guidelines,
            instructions=instructions,
        )