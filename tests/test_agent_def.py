from __future__ import annotations
"""Agent 定义解析测试。"""
import tempfile
from pathlib import Path
from src.SmallShrimp.utils.def_loader import AgentDef


def test_agent_def_from_file():
    """测试从 AGENT.md 文件加载 AgentDef。"""
    content = """---
name: Test Agent
description: A test agent for unit testing
llm:
  provider: openai
  model: gpt-4
  temperature: 0.7
capabilities:
  - coding
  - analysis
---

# Test Agent

You are a test agent.

## Guidelines

- Be helpful
- Be accurate

## Instructions

- Verify before executing
- Report progress
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        agent_file = Path(tmpdir) / "AGENT.md"
        agent_file.write_text(content)

        agent = AgentDef.from_file(agent_file)
        assert agent.name == "Test Agent"
        assert agent.description == "A test agent for unit testing"
        assert agent.llm["provider"] == "openai"
        assert agent.llm["model"] == "gpt-4"
        assert "coding" in agent.capabilities


def test_agent_def_guidelines_parsing():
    """测试 Guidelines 解析。"""
    content = """---
name: Guide Agent
description: Test guidelines
llm:
  provider: openai
---

## Guidelines

- Guideline one
- Guideline two
- Guideline three
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        agent = AgentDef._parse(content)
        assert len(agent.guidelines) == 3
        assert "Guideline one" in agent.guidelines


def test_agent_def_instructions_parsing():
    """测试 Instructions 解析。"""
    content = """---
name: Instruction Agent
description: Test instructions
llm:
  provider: openai
---

## Instructions

- Step one
- Step two
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        agent = AgentDef._parse(content)
        assert len(agent.instructions) == 2
        assert "Step one" in agent.instructions


def test_agent_def_invalid_format():
    """测试无效格式。"""
    content = "No frontmatter, just plain text"
    try:
        AgentDef._parse(content)
        assert False, "Should raise ValueError"
    except ValueError:
        pass


def test_agent_def_minimal():
    """测试最小化 AgentDef。"""
    content = """---
name: Minimal
description: Minimal agent
llm:
  provider: openai
---
"""
    agent = AgentDef._parse(content)
    assert agent.name == "Minimal"
    assert agent.guidelines == []
    assert agent.instructions == []


def test_agent_def_llm_config():
    """测试 LLM 配置提取。"""
    content = """---
name: LLM Config Agent
description: Test LLM config
llm:
  provider: deepseek
  model: deepseek-v3
  temperature: 0.5
  max_tokens: 2000
  context_window: 100000
---
"""
    agent = AgentDef._parse(content)
    assert agent.llm["provider"] == "deepseek"
    assert agent.llm["model"] == "deepseek-v3"
    assert agent.llm["temperature"] == 0.5
    assert agent.llm["max_tokens"] == 2000


if __name__ == "__main__":
    test_agent_def_from_file()
    test_agent_def_guidelines_parsing()
    test_agent_def_instructions_parsing()
    test_agent_def_invalid_format()
    test_agent_def_minimal()
    test_agent_def_llm_config()
    print("\nAll test_agent_def tests passed!")