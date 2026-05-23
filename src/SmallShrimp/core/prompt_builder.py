"""Prompt builder that assembles system prompt from layers."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pathlib import Path

if TYPE_CHECKING:
    from .events import EventSource
    from .session_state import SessionState


class PromptBuilder:
    """Assembles system prompt from layered sources.

    Layers:
    1. Identity: agent_md from AGENT.md
    2. Personality: soul_md from SOUL.md (optional)
    3. Bootstrap: BOOTSTRAP.md + AGENTS.md + cron list
    4. Runtime: agent_id + timestamp
    5. Channel hint: platform/cron/agent context
    """

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def build(self, state: "SessionState") -> str:
        """Build the full system prompt from layers."""
        agent_def = state.agent.agent_def
        layers: list[str] = []

        # Layer 1: Identity (agent_md from AGENT.md body)
        agent_md = getattr(agent_def, "agent_md", None)
        if agent_md:
            layers.append(agent_md)
        else:
            # Fallback: build from legacy fields
            layers.append(self._build_legacy_identity(agent_def))

        # Layer 2: Soul / Personality (optional)
        soul_md = getattr(agent_def, "soul_md", "")
        if soul_md:
            layers.append(f"## Personality\n\n{soul_md}")

        # Layer 3: Bootstrap context
        bootstrap = self._load_bootstrap_context()
        if bootstrap:
            layers.append(bootstrap)

        # Layer 4: Runtime context
        agent_id = getattr(agent_def, "id", agent_def.name)
        session_time = getattr(state, "created_at", datetime.now().isoformat())
        layers.append(
            f"## Runtime\n\nAgent: {agent_id}\nTime: {session_time}"
        )

        # Layer 5: Channel hint
        if state.source is not None:
            layers.append(self._build_channel_hint(state.source))

        # Layer 6: User Profile（稳定用户画像）
        profile_block = self._build_profile_block(state)
        if profile_block:
            layers.append(profile_block)

        # Layer 7: Memory guidelines（记忆工具使用指南）
        if getattr(state.agent, "memory_manager", None):
            layers.append(
                "## 记忆指南\n\n"
                "记忆分为用户画像和任务记忆，两条通道不要混用。\n"
                "- 用户画像已在本提示的 `User Profile` 中稳定列出，优先相信。\n"
                "- remember_profile(content)：只保存姓名、长期偏好、沟通语言、明确纠正。\n"
                "- remember_fact(content)：保存普通跨会话事实。\n"
                "- remember_project(content)：保存当前项目/仓库上下文。\n"
                "- remember_reflection(content)：保存失败模式、工具教训、行为反思。\n"
                "- recall_memory(query)：只检索任务记忆，不检索用户画像。\n"
                "- consolidate_memories：清理非画像记忆库中的重复记录。\n"
                "不要保存可从当前上下文推导的临时信息。"
            )

        return "\n\n".join(layers)

    def _build_legacy_identity(self, agent_def) -> str:
        """Build identity from legacy AgentDef fields (backward compat)."""
        parts = [
            f"You are {agent_def.name}.",
            agent_def.description,
        ]

        if agent_def.guidelines:
            parts.append("\n## Guidelines")
            for g in agent_def.guidelines:
                parts.append(f"- {g}")

        if agent_def.instructions:
            parts.append("\n## Instructions")
            for i in agent_def.instructions:
                parts.append(f"- {i}")

        return "\n".join(parts)

    def _load_bootstrap_context(self) -> str:
        """Load BOOTSTRAP.md + AGENTS.md from workspace."""
        parts: list[str] = []

        bootstrap_path = self.workspace / "BOOTSTRAP.md"
        if bootstrap_path.exists():
            parts.append(bootstrap_path.read_text(encoding="utf-8").strip())

        agents_path = self.workspace / "AGENTS.md"
        if agents_path.exists():
            parts.append(agents_path.read_text(encoding="utf-8").strip())

        return "\n\n".join(parts)

    def _build_profile_block(self, state: "SessionState") -> str:
        """注入用户画像到 system prompt。"""
        memory_manager = getattr(state.agent, "memory_manager", None)
        if memory_manager is None:
            return ""
        profile = memory_manager.get_profile()
        if not profile:
            return ""
        lines = ["## User Profile\n"]
        for r in profile:
            lines.append(f"- {r['content']}")
        return "\n".join(lines)

    def _build_channel_hint(self, source: "EventSource") -> str:
        """Build platform/channel hint for the agent."""
        if source.is_cron:
            return (
                "You are running as a background cron job. "
                "Your response will not be sent to a user directly."
            )
        if source.is_agent:
            return (
                "You are running as a dispatched subagent. "
                "Your response will be sent to the main agent."
            )
        if source.is_platform:
            return f"You are responding via {source.platform_name}."
        return f"You are responding via {source._namespace}."
