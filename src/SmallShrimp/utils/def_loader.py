from __future__ import annotations
"""Agent 定义加载器。"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml

@dataclass
class AgentDef:
    id: str = ""  # folder name / agent identifier
    name: str = ""
    description: str = ""
    llm: dict[str, Any] = field(default_factory=dict)
    tools: list[str] = field(default_factory=list)  # 空=共享全部
    capabilities: list[str] = field(default_factory=list)
    guidelines: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    agent_md: str = ""  # raw AGENT.md body (full markdown)
    soul_md: str = ""  # SOUL.md content (optional personality layer)
    max_concurrency: int = 1  # max concurrent sessions for this agent

    @classmethod
    def from_file(cls, path: str | Path) -> "AgentDef":
        path = Path(path)
        content = path.read_text(encoding="utf-8")
        agent_id = path.parent.name  # folder name is the agent id
        return cls._parse(content, agent_id=agent_id)

    @classmethod
    def _parse(cls, content: str, agent_id: str = "") -> "AgentDef":
        pattern = r"^---\n(.*?)---\n(.*)$"
        match = re.match(pattern, content, re.DOTALL)
        if not match:
            raise ValueError("Invalid AGENT.md format")

        frontmatter = yaml.safe_load(match.group(1))
        body = match.group(2).strip()

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
            id=agent_id,
            name=frontmatter.get("name", ""),
            description=frontmatter.get("description", ""),
            llm=frontmatter.get("llm", {}),
            tools=frontmatter.get("tools", []),
            capabilities=frontmatter.get("capabilities", []),
            guidelines=guidelines,
            instructions=instructions,
            agent_md=body,
            soul_md="",  # loaded separately by AgentLoader
        )