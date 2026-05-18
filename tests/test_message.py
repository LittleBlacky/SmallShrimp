from __future__ import annotations
"""Message 类测试。"""
from src.SmallShrimp.core.message import (
    SystemMessage, HumanMessage, AssistantMessage, ToolMessage
)


def test_system_message():
    """测试系统消息。"""
    msg = SystemMessage(content="You are a helpful assistant")
    assert msg.content == "You are a helpful assistant"
    assert msg.to_dict() == {
        "role": "system",
        "content": "You are a helpful assistant"
    }


def test_human_message():
    """测试用户消息。"""
    msg = HumanMessage(content="Hello")
    assert msg.content == "Hello"
    assert msg.to_dict() == {
        "role": "user",
        "content": "Hello"
    }


def test_assistant_message():
    """测试助手消息。"""
    msg = AssistantMessage(content="Hi there!")
    assert msg.content == "Hi there!"
    assert msg.to_dict() == {
        "role": "assistant",
        "content": "Hi there!"
    }


def test_assistant_message_with_tool_calls():
    """测试带工具调用的助手消息。"""
    tool_calls = [
        {
            "id": "call_123",
            "type": "function",
            "function": {"name": "read", "arguments": '{"file_path": "test.txt"}'}
        }
    ]
    msg = AssistantMessage(content="Reading file...", tool_calls=tool_calls)
    assert msg.tool_calls == tool_calls
    assert msg.to_dict()["tool_calls"] == tool_calls


def test_assistant_message_with_reasoning():
    """测试带思考内容的助手消息（DeepSeek）。"""
    msg = AssistantMessage(
        content="Final answer",
        reasoning_content="Let me think step by step..."
    )
    assert msg.reasoning_content == "Let me think step by step..."
    assert "reasoning_content" in msg.to_dict()
    assert msg.to_dict()["reasoning_content"] == "Let me think step by step..."


def test_tool_message():
    """测试工具消息。"""
    msg = ToolMessage(
        content="File contents: Hello World",
        tool_call_id="call_123",
        name="read"
    )
    assert msg.content == "File contents: Hello World"
    assert msg.tool_call_id == "call_123"
    assert msg.name == "read"
    assert msg.to_dict() == {
        "role": "tool",
        "content": "File contents: Hello World",
        "tool_call_id": "call_123",
        "name": "read"
    }


def test_tool_message_defaults():
    """测试工具消息默认值。"""
    msg = ToolMessage(content="result")
    assert msg.tool_call_id == ""
    assert msg.name == ""


if __name__ == "__main__":
    test_system_message()
    test_human_message()
    test_assistant_message()
    test_assistant_message_with_tool_calls()
    test_assistant_message_with_reasoning()
    test_tool_message()
    test_tool_message_defaults()
    print("\nAll test_message tests passed!")
