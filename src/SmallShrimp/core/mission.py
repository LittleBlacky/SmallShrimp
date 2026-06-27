"""Agent Mission — "why it exists" separated from "how it works".

Inspired by llm_wiki's purpose.md concept. The mission is injected
into the system prompt as a permanent cache segment.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentMission:
    """Defines the agent's purpose, scope, and constraints."""
    goals: list[str] = field(default_factory=list)
    key_questions: list[str] = field(default_factory=list)
    scope: str = ""
    constraints: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.goals and not self.key_questions and not self.scope

    def render(self) -> str:
        """Render mission as a system prompt segment."""
        if self.is_empty():
            return ""

        lines = ["## Mission\n"]

        if self.goals:
            lines.append("**目标:**")
            for g in self.goals:
                lines.append(f"- {g}")
            lines.append("")

        if self.key_questions:
            lines.append("**核心问题:**")
            for q in self.key_questions:
                lines.append(f"- {q}")
            lines.append("")

        if self.scope:
            lines.append(f"**范围:** {self.scope}\n")

        if self.constraints:
            lines.append("**约束:**")
            for c in self.constraints:
                lines.append(f"- {c}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def from_mapping(data: dict) -> "AgentMission":
        """Parse from AGENT.md frontmatter `mission:` field."""
        if not data or not isinstance(data, dict):
            return AgentMission()

        goals = data.get("goals", [])
        if isinstance(goals, str):
            goals = [goals]

        questions = data.get("key_questions", [])
        if isinstance(questions, str):
            questions = [questions]

        constraints = data.get("constraints", [])
        if isinstance(constraints, str):
            constraints = [constraints]

        return AgentMission(
            goals=goals,
            key_questions=questions,
            scope=str(data.get("scope", "")),
            constraints=constraints,
        )
