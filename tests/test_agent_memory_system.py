"""Agent-level memory integration tests.

These tests exercise the real AgentSession.chat loop with a fake LLM so memory
is validated as part of prompt construction, tool schemas, tool execution, and
subsequent turns without calling an external model provider.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.SmallShrimp.core.agent import AgentSession
from src.SmallShrimp.core.context_guard import ContextGuard
from src.SmallShrimp.core.memory.memory_manager import MemoryManager
from src.SmallShrimp.core.permissions import PermissionChecker, PermissionMode
from src.SmallShrimp.core.prompt_builder import PromptBuilder
from src.SmallShrimp.core.session_state import SessionState
from src.SmallShrimp.tools.decorators import tool
from src.SmallShrimp.tools.memory_tool import create_memory_tools
from src.SmallShrimp.tools.registry import ToolRegistry


class FakeThinkingStrategy:
    def prepare_reasoning_message(self, reasoning_content):
        if reasoning_content:
            return {"role": "assistant", "content": "", "reasoning_content": reasoning_content}
        return None


class FakeDeepSeekLLM:
    """Scripted LLM with DeepSeek-style reasoning behavior."""

    def __init__(self, responses: list[dict]):
        self.responses = responses
        self.calls: list[dict] = []
        self.thinking_strategy = FakeThinkingStrategy()

    async def chat(self, messages, tools=None, reasoning_content=None, **kwargs):
        self.calls.append({
            "messages": messages,
            "tools": tools or [],
            "reasoning_content": reasoning_content,
        })
        if not self.responses:
            raise AssertionError("FakeDeepSeekLLM has no scripted response left")
        return self.responses.pop(0)


class NoopFailureLearner:
    def observe_turn(self, failures):
        return []


class NoopTrustManager:
    def is_trusted(self, path):
        return True

    def scan_dangerous(self, path):
        return []

    def trust(self, path):
        return None


class NoopMcpManager:
    pass


def _tool_call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


def _make_session(memory: MemoryManager, llm: FakeDeepSeekLLM, workspace: Path) -> AgentSession:
    registry = ToolRegistry()
    for tool in create_memory_tools(memory):
        registry.register(tool)

    agent_def = SimpleNamespace(
        id="pickle",
        name="Pickle",
        description="Test agent",
        agent_md="# Pickle\n\n你是 Pickle。",
        soul_md="",
        guidelines=[],
        instructions=[],
        llm={"context_window": 200000},
    )
    agent = SimpleNamespace(
        agent_def=agent_def,
        memory_manager=memory,
        tool_registry=registry,
        llm=llm,
        context_guard=ContextGuard(token_threshold=160000),
        failure_learner=NoopFailureLearner(),
        history_manager=None,
        trust_manager=NoopTrustManager(),
        permission_checker=PermissionChecker(PermissionMode.DEFAULT),
        mcp_manager=NoopMcpManager(),
        _mcp_registered=True,
    )
    state = SessionState(
        session_id="agent-memory-e2e",
        agent=agent,
        prompt_builder=PromptBuilder(workspace),
    )
    return AgentSession(agent=agent, state=state)


@pytest.mark.asyncio
async def test_agent_chat_writes_profile_then_prompt_uses_it_next_turn(workspace_tmp):
    workspace = workspace_tmp
    memory = MemoryManager(workspace / "memories")
    llm = FakeDeepSeekLLM([
        {
            "content": "",
            "tool_calls": [_tool_call("call-profile", "remember_profile", {"content": "用户叫 Zane"})],
            "finish_reason": "tool_calls",
            "reasoning_content": "用户明确要求记住姓名，应写入 profile。",
            "should_store_reasoning": True,
        },
        {"content": "已记住你的名字。", "tool_calls": None, "finish_reason": "stop", "reasoning_content": None, "should_store_reasoning": False},
        {"content": "你叫 Zane。", "tool_calls": None, "finish_reason": "stop", "reasoning_content": None, "should_store_reasoning": False},
    ])
    session = _make_session(memory, llm, workspace)

    first_answer = await session.chat("记住我叫 Zane")
    assert first_answer == "已记住你的名字。"
    assert any(record["content"] == "用户叫 Zane" for record in memory.get_profile())

    second_answer = await session.chat("我叫什么？")
    assert second_answer == "你叫 Zane。"
    second_turn_system_prompt = llm.calls[2]["messages"][0]["content"]
    # Profile written in-turn is NOT injected into system prompt (frozen snapshot)
    # LLM learns about it via tool call history instead
    assert "## User Profile" not in second_turn_system_prompt


@pytest.mark.asyncio
async def test_agent_chat_recalls_task_memory_but_not_profile(workspace_tmp):
    workspace = workspace_tmp
    memory = MemoryManager(workspace / "memories")
    memory.remember_profile("用户叫 Zane")
    memory.remember_project("SmallShrimp 使用 pytest 运行测试")
    llm = FakeDeepSeekLLM([
        {
            "content": "",
            "tool_calls": [_tool_call("call-recall", "recall_memory", {"query": "SmallShrimp 测试"})],
            "finish_reason": "tool_calls",
            "reasoning_content": "需要项目测试信息，调用任务记忆召回。",
            "should_store_reasoning": False,
        },
        {"content": "这个项目使用 pytest 运行测试。", "tool_calls": None, "finish_reason": "stop", "reasoning_content": None, "should_store_reasoning": False},
    ])
    session = _make_session(memory, llm, workspace)

    answer = await session.chat("这个项目测试怎么跑？")
    assert answer == "这个项目使用 pytest 运行测试。"

    tool_messages = [message for message in session.state.messages if getattr(message, "name", "") == "recall_memory"]
    assert len(tool_messages) == 1
    assert "SmallShrimp 使用 pytest" in tool_messages[0].content
    assert "用户叫 Zane" not in tool_messages[0].content

    first_system_prompt = llm.calls[0]["messages"][0]["content"]
    assert "用户叫 Zane" in first_system_prompt
    tool_names = {schema["function"]["name"] for schema in llm.calls[0]["tools"]}
    assert "remember_profile" in tool_names
    assert "remember_fact" in tool_names
    assert "remember_project" in tool_names
    assert "remember_reflection" in tool_names
    assert "remember" not in tool_names


@pytest.mark.asyncio
async def test_agent_chat_does_not_repeat_surfaced_task_memory(workspace_tmp):
    workspace = workspace_tmp
    memory = MemoryManager(workspace / "memories")
    memory.remember_project("SmallShrimp 使用 pytest 运行测试")
    llm = FakeDeepSeekLLM([
        {
            "content": "",
            "tool_calls": [_tool_call("call-recall-1", "recall_memory", {"query": "SmallShrimp 测试"})],
            "finish_reason": "tool_calls",
            "reasoning_content": "第一次召回项目测试信息。",
            "should_store_reasoning": False,
        },
        {
            "content": "",
            "tool_calls": [_tool_call("call-recall-2", "recall_memory", {"query": "SmallShrimp 测试"})],
            "finish_reason": "tool_calls",
            "reasoning_content": "再次查询相同信息。",
            "should_store_reasoning": False,
        },
        {"content": "已确认。", "tool_calls": None, "finish_reason": "stop", "reasoning_content": None, "should_store_reasoning": False},
    ])
    session = _make_session(memory, llm, workspace)

    answer = await session.chat("这个项目测试怎么跑？")
    assert answer == "已确认。"

    tool_messages = [message for message in session.state.messages if getattr(message, "name", "") == "recall_memory"]
    assert len(tool_messages) == 2
    assert "SmallShrimp 使用 pytest" in tool_messages[0].content
    assert tool_messages[1].content == "未找到相关任务记忆。"
    assert len(session.state.surfaced_memory_ids) == 1
    assert session.state.session_memory_bytes > 0


@pytest.mark.asyncio
async def test_agent_chat_budgets_tool_results_across_session(workspace_tmp):
    workspace = workspace_tmp
    memory = MemoryManager(workspace / "memories")
    llm = FakeDeepSeekLLM([
        {
            "content": "",
            "tool_calls": [
                _tool_call("call-large-1", "large_output", {}),
                _tool_call("call-large-2", "large_output", {}),
            ],
            "finish_reason": "tool_calls",
            "reasoning_content": "需要读取大输出。",
            "should_store_reasoning": False,
        },
        {"content": "已处理。", "tool_calls": None, "finish_reason": "stop", "reasoning_content": None, "should_store_reasoning": False},
    ])
    session = _make_session(memory, llm, workspace)
    session.state.max_session_tool_result_bytes = 1000

    @tool(description="Return a large test payload.")
    async def large_output() -> str:
        return "x" * 2000

    session.agent.tool_registry.register(large_output)

    answer = await session.chat("读取大输出")
    assert answer == "已处理。"

    tool_messages = [message for message in session.state.messages if getattr(message, "name", "") == "large_output"]
    assert len(tool_messages) == 2
    assert "tool result budgeted" in tool_messages[0].content
    assert "result omitted" in tool_messages[1].content
    assert session.state.session_tool_result_bytes == session.state.max_session_tool_result_bytes

    second_call_messages = llm.calls[1]["messages"]
    tool_payloads = [message["content"] for message in second_call_messages if message.get("name") == "large_output"]
    assert "tool result budgeted" in tool_payloads[0]
    assert "result omitted" in tool_payloads[1]

