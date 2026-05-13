from abc import ABC, abstractmethod
from dataclasses import dataclass

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
    def to_dict(self) -> dict:
        return {"role": "assistant", "content": self.content}
        
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