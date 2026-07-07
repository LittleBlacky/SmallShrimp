from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List

class Message(ABC):
    @abstractmethod
    def to_dict(self) -> dict:
        ...

@dataclass
class SystemMessage(Message):
    """系统提示。"""
    content: str
    def to_dict(self) -> dict:
        return {"role": "system", "content": self.content}

@dataclass
class HumanMessage(Message):
    """用户消息。"""
    content: str
    def to_dict(self) -> dict:
        return {"role": "user", "content": self.content}

@dataclass
class AssistantMessage(Message):
    """助手消息。"""
    content: str
    tool_calls: Optional[List] = None
    reasoning_content: Optional[str] = None  # DeepSeek 思考内容

    def to_dict(self) -> dict:
        result = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        # DeepSeek 思考模式需要传回 reasoning_content
        if self.reasoning_content:
            result["reasoning_content"] = self.reasoning_content
        return result
        
@dataclass
class ToolMessage(Message):
    """工具调用结果。"""
    content: str
    tool_call_id: str = ""
    name: str = ""
    def to_dict(self) -> dict:
        return {
            "role": "tool",
            "content": self.content,
            "tool_call_id": self.tool_call_id,
            "name": self.name,
        }