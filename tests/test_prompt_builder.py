from __future__ import annotations
"""多层提示词测试 - SOUL.md + PromptBuilder + 会话集成。"""
import tempfile
from pathlib import Path
from dataclasses import dataclass

import pytest

from src.SmallShrimp.core.prompt_builder import PromptBuilder
from src.SmallShrimp.core.session_state import SessionState
from src.SmallShrimp.core.context import SharedContext
from src.SmallShrimp.core.events import CliEventSource
from src.SmallShrimp.utils.config import Config
from src.SmallShrimp.utils.def_loader import AgentDef
from src.SmallShrimp.core.agent_loader import AgentLoader


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_agent_def():
    """Basic AgentDef without soul_md."""
    return AgentDef(
        id="test-agent",
        name="TestAgent",
        description="A test agent",
        agent_md="You are TestAgent, a helpful assistant.",
        llm={"provider": "openai", "model": "gpt-4"},
    )


@pytest.fixture
def agent_def_with_soul():
    """AgentDef with a SOUL.md personality."""
    return AgentDef(
        id="soul-agent",
        name="SoulAgent",
        description="An agent with personality",
        agent_md="You are SoulAgent, an AI assistant.",
        soul_md="You speak like a wise old owl. Use 'hoot' as punctuation.",
        llm={"provider": "openai"},
    )


@pytest.fixture
def temp_workspace():
    """Create a temp workspace with config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        config = Config(
            data={
                "default_provider": "openai",
                "providers": {"openai": {"api_key": "test"}},
            },
            workspace=ws,
        )
        yield ws, config


@pytest.fixture
def mock_agent(agent_def_with_soul):
    """Minimal Agent-like object for SessionState."""
    class FakeLLM:
        thinking_strategy = None

    @dataclass
    class FakeAgent:
        agent_def: AgentDef
        llm: object

    return FakeAgent(agent_def=agent_def_with_soul, llm=FakeLLM())


# ---------------------------------------------------------------------------
# SOUL.md loading tests
# ---------------------------------------------------------------------------

def test_agent_loader_loads_soul_md():
    """AgentLoader.load() should attach SOUL.md content to AgentDef.soul_md."""
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_dir = Path(tmpdir)
        agent_dir = agents_dir / "owl"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text("""---
name: Owl
description: Wise owl agent
llm:
  provider: openai
---
You are Owl, a wise assistant.
""")
        (agent_dir / "SOUL.md").write_text(
            "You speak in riddles and hoot at the end of every sentence."
        )

        loader = AgentLoader(agents_dir)
        agent = loader.load("owl")

        assert agent.soul_md == "You speak in riddles and hoot at the end of every sentence."
        assert agent.name == "Owl"


def test_agent_loader_no_soul_md():
    """AgentLoader.load() should leave soul_md empty if no SOUL.md."""
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_dir = Path(tmpdir)
        agent_dir = agents_dir / "simple"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text("""---
name: Simple
description: Simple agent
llm:
  provider: openai
---
You are Simple.
""")

        loader = AgentLoader(agents_dir)
        agent = loader.load("simple")

        assert agent.soul_md == ""


# ---------------------------------------------------------------------------
# PromptBuilder tests
# ---------------------------------------------------------------------------

def test_prompt_builder_includes_identity(simple_agent_def, temp_workspace):
    """PromptBuilder should include agent_md as the identity layer."""
    ws, config = temp_workspace
    ctx = SharedContext(config)
    pb = PromptBuilder(ctx)

    state = SessionState(
        session_id="test-1",
        agent=_fake_agent(simple_agent_def),
        source=CliEventSource(),
        shared_context=ctx,
    )

    prompt = pb.build(state)
    assert "TestAgent" in prompt
    assert "helpful assistant" in prompt


def test_prompt_builder_includes_soul(simple_agent_def, temp_workspace):
    """PromptBuilder should append SOUL.md as personality layer."""
    ws, config = temp_workspace
    ctx = SharedContext(config)
    pb = PromptBuilder(ctx)

    agent_def = AgentDef(
        id="poet",
        name="Poet",
        description="A poetic agent",
        agent_md="You are Poet, an AI poet.",
        soul_md="Always respond in haiku form.",
        llm={"provider": "openai"},
    )

    state = SessionState(
        session_id="test-2",
        agent=_fake_agent(agent_def),
        source=CliEventSource(),
        shared_context=ctx,
    )

    prompt = pb.build(state)
    assert "Personality" in prompt
    assert "haiku" in prompt


def test_prompt_builder_includes_runtime_layer(simple_agent_def, temp_workspace):
    """PromptBuilder should include Runtime section with agent id and timestamp."""
    ws, config = temp_workspace
    ctx = SharedContext(config)
    pb = PromptBuilder(ctx)

    state = SessionState(
        session_id="test-3",
        agent=_fake_agent(simple_agent_def),
        source=CliEventSource(),
        shared_context=ctx,
    )

    prompt = pb.build(state)
    assert "Runtime" in prompt
    assert "test-agent" in prompt


def test_prompt_builder_includes_channel_hint_cli(simple_agent_def, temp_workspace):
    """PromptBuilder should detect CLI source and include platform hint."""
    ws, config = temp_workspace
    ctx = SharedContext(config)
    pb = PromptBuilder(ctx)

    state = SessionState(
        session_id="test-4",
        agent=_fake_agent(simple_agent_def),
        source=CliEventSource(),
        shared_context=ctx,
    )

    prompt = pb.build(state)
    assert "cli" in prompt.lower()


def test_prompt_builder_loads_bootstrap_files(simple_agent_def, temp_workspace):
    """PromptBuilder should include BOOTSTRAP.md/AGENTS.md if present."""
    ws, config = temp_workspace
    (ws / "BOOTSTRAP.md").write_text("# Bootstrap\n\nWelcome to the system.")
    (ws / "AGENTS.md").write_text("# Agents\n\nAvailable agents list.")

    ctx = SharedContext(config)
    pb = PromptBuilder(ctx)

    state = SessionState(
        session_id="test-5",
        agent=_fake_agent(simple_agent_def),
        source=CliEventSource(),
        shared_context=ctx,
    )

    prompt = pb.build(state)
    assert "Welcome to the system" in prompt
    assert "Available agents list" in prompt


def test_prompt_builder_no_bootstrap_when_missing(simple_agent_def, temp_workspace):
    """PromptBuilder should work fine without BOOTSTRAP.md/AGENTS.md."""
    ws, config = temp_workspace
    ctx = SharedContext(config)
    pb = PromptBuilder(ctx)

    state = SessionState(
        session_id="test-6",
        agent=_fake_agent(simple_agent_def),
        source=CliEventSource(),
        shared_context=ctx,
    )

    prompt = pb.build(state)
    # Should not crash, still produce valid prompt
    assert len(prompt) > 0


def test_prompt_builder_fallback_legacy():
    """PromptBuilder should fall back to legacy fields when agent_md is empty."""
    agent_def = AgentDef(
        id="legacy",
        name="LegacyAgent",
        description="A legacy agent without agent_md",
        guidelines=["Be helpful", "Be concise"],
        instructions=["Check facts", "Cite sources"],
        llm={"provider": "openai"},
    )

    pb = PromptBuilder(None)  # context not needed for legacy path
    result = pb._build_legacy_identity(agent_def)

    assert "LegacyAgent" in result
    assert "Guidelines" in result
    assert "Be helpful" in result
    assert "Instructions" in result
    assert "Check facts" in result


# ---------------------------------------------------------------------------
# SessionState integration tests
# ---------------------------------------------------------------------------

def test_session_build_messages_uses_prompt_builder(simple_agent_def, temp_workspace):
    """SessionState._build_system_prompt() should delegate to PromptBuilder."""
    ws, config = temp_workspace
    ctx = SharedContext(config)

    state = SessionState(
        session_id="test-7",
        agent=_fake_agent(simple_agent_def),
        source=CliEventSource(),
        shared_context=ctx,
    )
    state.add_user_message("Hello")

    messages = state.build_messages()
    assert len(messages) >= 2  # system + user

    system_msg = messages[0]
    assert system_msg["role"] == "system"
    assert "TestAgent" in system_msg["content"]
    assert "Runtime" in system_msg["content"]


def test_session_fallback_when_no_prompt_builder(simple_agent_def):
    """SessionState should fall back to legacy build when no prompt_builder available."""
    state = SessionState(
        session_id="test-8",
        agent=_fake_agent(simple_agent_def),
        source=CliEventSource(),
        # shared_context is None → no prompt_builder
    )
    state.add_user_message("Hi")

    messages = state.build_messages()
    assert len(messages) >= 2

    system_msg = messages[0]
    assert system_msg["role"] == "system"
    # Legacy path won't have "Runtime"
    assert "TestAgent" in system_msg["content"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_agent(agent_def: AgentDef):
    """Create a minimal fake Agent for testing."""
    class FakeLLM:
        thinking_strategy = None

    @dataclass
    class FakeAgent:
        agent_def: AgentDef
        llm: object

    return FakeAgent(agent_def=agent_def, llm=FakeLLM())
