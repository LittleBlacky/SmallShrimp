from __future__ import annotations
"""Agent 加载器测试。"""
import tempfile
from pathlib import Path
from src.SmallShrimp.core.agent_loader import AgentLoader


def create_agent_dir(parent: Path, name: str, content: str) -> Path:
    """创建测试用 agent 目录和文件。"""
    agent_dir = parent / name
    agent_dir.mkdir()
    agent_file = agent_dir / "AGENT.md"
    agent_file.write_text(content)
    return agent_dir


def test_agent_loader_load():
    """测试加载单个 Agent。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_dir = Path(tmpdir)
        create_agent_dir(agents_dir, "test-agent", """---
name: Test Agent
description: Test agent description
llm:
  provider: openai
  model: gpt-4
capabilities:
  - testing
---

## Guidelines

- Test guideline
""")

        loader = AgentLoader(agents_dir)
        agent = loader.load("test-agent")

        assert agent.name == "Test Agent"
        assert agent.description == "Test agent description"


def test_agent_loader_load_not_found():
    """测试加载不存在的 Agent。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        loader = AgentLoader(Path(tmpdir))
        try:
            loader.load("nonexistent")
            assert False, "Should raise FileNotFoundError"
        except FileNotFoundError:
            pass


def test_agent_loader_list_agents():
    """测试列出所有 Agent。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_dir = Path(tmpdir)
        create_agent_dir(agents_dir, "agent-one", """---
name: Agent One
description: First agent
llm:
  provider: openai
---""")
        create_agent_dir(agents_dir, "agent-two", """---
name: Agent Two
description: Second agent
llm:
  provider: openai
---""")

        loader = AgentLoader(agents_dir)
        names = loader.list_agents()

        assert len(names) == 2
        assert "agent-one" in names
        assert "agent-two" in names


def test_agent_loader_list_empty():
    """测试空目录。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        loader = AgentLoader(Path(tmpdir))
        names = loader.list_agents()
        assert len(names) == 0


def test_agent_loader_list_no_dir():
    """测试不存在的目录。"""
    loader = AgentLoader(Path("/nonexistent/agents"))
    names = loader.list_agents()
    assert len(names) == 0


def test_agent_loader_ignores_files():
    """测试忽略非目录文件。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_dir = Path(tmpdir)
        (agents_dir / "not-an-agent.txt").write_text("not an agent")
        create_agent_dir(agents_dir, "valid-agent", """---
name: Valid Agent
description: Valid
llm:
  provider: openai
---""")

        loader = AgentLoader(agents_dir)
        names = loader.list_agents()

        assert len(names) == 1
        assert "valid-agent" in names


if __name__ == "__main__":
    test_agent_loader_load()
    test_agent_loader_load_not_found()
    test_agent_loader_list_agents()
    test_agent_loader_list_empty()
    test_agent_loader_list_no_dir()
    test_agent_loader_ignores_files()
    print("\nAll test_agent_loader tests passed!")