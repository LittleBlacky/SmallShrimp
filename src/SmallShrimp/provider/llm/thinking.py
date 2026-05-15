
from abc import ABC, abstractmethod
from typing import Any


class ThinkingStrategy(ABC):
    """思考模式处理策略基类"""

    @abstractmethod
    def prepare_request(self, reasoning_content: str | None) -> dict | None:
        """准备请求参数，返回 thinking 参数或 None"""
        pass

    @abstractmethod
    def extract_reasoning_content(self, response: Any) -> str | None:
        """从响应中提取思考内容"""
        pass

    @abstractmethod
    def should_store_response(self, response: Any) -> bool:
        """判断是否需要保存本次响应的思考内容（用于下一轮请求）"""
        pass

    @abstractmethod
    def prepare_reasoning_message(self, reasoning_content: str | None) -> dict | None:
        """为需要传回 reasoning_content 的 provider，准备 assistant 消息"""
        pass


class DeepSeekThinkingStrategy(ThinkingStrategy):
    """DeepSeek: 思考模式

    DeepSeek 的思考模式需要在每次请求中传入：
    - 每次请求: thinking = {"type": "enabled", "budget_tokens": 1024}
    - Assistant 消息: 需要包含 reasoning_content 字段

    DeepSeek API 要求：如果响应包含 reasoning_content，
    下次请求的对应 assistant 消息必须包含该字段
    """

    def __init__(self, budget_tokens: int = 1024):
        self.budget_tokens = budget_tokens

    def prepare_request(self, reasoning_content: str | None) -> dict | None:
        # DeepSeek 每次请求都需要 thinking 参数来启用思考模式
        return {
            "thinking": {
                "type": "enabled",
                "budget_tokens": self.budget_tokens
            }
        }

    def extract_reasoning_content(self, response: Any) -> str | None:
        """从 litellm 响应对象中提取 reasoning_content"""
        try:
            choice = getattr(response, "choices", [None])[0]
            if choice:
                message = choice.message
                return getattr(message, "reasoning_content", None)
        except (IndexError, AttributeError):
            pass
        return None

    def should_store_response(self, response: Any) -> bool:
        # DeepSeek 响应包含 reasoning_content 时需要保存
        reasoning = self.extract_reasoning_content(response)
        return reasoning is not None and reasoning != ""

    def prepare_reasoning_message(self, reasoning_content: str | None) -> dict | None:
        """DeepSeek: 需要传回 reasoning_content"""
        if reasoning_content:
            return {"role": "assistant", "content": "", "reasoning_content": reasoning_content}
        return None


class AnthropicThinkingStrategy(ThinkingStrategy):
    """Claude: 只读 thinking，不需要传回"""

    def prepare_request(self, reasoning_content: str | None) -> dict | None:
        # Claude 需要 thinking 预算，不需要传回之前的 reasoning_content
        return {"thinking": {"type": "enabled", "budget_tokens": 1024}}

    def extract_reasoning_content(self, response: Any) -> str | None:
        # Claude 的 thinking 在 message.additional_kwargs 中
        message = getattr(response, "choices", [None])[0]
        if message:
            message = message.message
            additional = getattr(message, "additional_kwargs", {})
            return additional.get("thinking")
        return None

    def should_store_response(self, response: Any) -> bool:
        # Claude 思考完成后，继续生成最终回答，不需要保存
        return False

    def prepare_reasoning_message(self, reasoning_content: str | None) -> dict | None:
        """Claude: 不需要传回 reasoning_content"""
        return None


class GeminiThinkingStrategy(ThinkingStrategy):
    """Gemini: 通过配置开启思考"""

    def prepare_request(self, reasoning_content: str | None) -> dict | None:
        # Gemini 通过 thinking_strategy 配置开启思考
        return {
            "thinking_config": {
                "thinking_budget": 1024,
            }
        }

    def extract_reasoning_content(self, response: Any) -> str | None:
        # Gemini 的思考内容可能在特定字段中
        message = getattr(response, "choices", [None])[0]
        if message:
            message = message.message
            return getattr(message, "prompt_feedback", None)
        return None

    def should_store_response(self, response: Any) -> bool:
        return False

    def prepare_reasoning_message(self, reasoning_content: str | None) -> dict | None:
        """Gemini: 不需要传回 reasoning_content"""
        return None


class NoOpThinkingStrategy(ThinkingStrategy):
    """其他 LLM: 不需要处理"""

    def prepare_request(self, reasoning_content: str | None) -> None:
        return None

    def extract_reasoning_content(self, response: Any) -> str | None:
        return None

    def should_store_response(self, response: Any) -> bool:
        return False

    def prepare_reasoning_message(self, reasoning_content: str | None) -> dict | None:
        """通用: 不需要传回 reasoning_content"""
        return None


# 工厂函数
_PROVIDER_STRATEGIES = {
    "deepseek": DeepSeekThinkingStrategy,
    "anthropic": AnthropicThinkingStrategy,
    "google": GeminiThinkingStrategy,
    "gemini": GeminiThinkingStrategy,
}


def create_thinking_strategy(provider: str) -> ThinkingStrategy:
    """根据 provider 创建对应的思考策略"""
    strategy_class = _PROVIDER_STRATEGIES.get(provider.lower())
    if strategy_class:
        return strategy_class()
    return NoOpThinkingStrategy()