from dataclasses import dataclass
from typing import Any

import yaml
from litellm import acompletion
from litellm.types.completion import ChatCompletionMessageParam as Message

from .thinking import ThinkingStrategy, NoOpThinkingStrategy, create_thinking_strategy


@dataclass
class LLMConfig:
    provider: str
    model: str
    api_key: str
    api_base: str | None = None
    temperature: float = 0.7
    max_tokens: int = 20000

    @classmethod
    def from_yaml(cls, path: str) -> "LLMConfig":
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data["llm"])


class LLMProvider:

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.model = config.model
        self.api_key = config.api_key
        self.api_base = config.api_base
        self.thinking_strategy: ThinkingStrategy = create_thinking_strategy(config.provider)

    @classmethod
    def from_config(cls, config: LLMConfig) -> "LLMProvider":
        return cls(config)

    async def chat(self, messages: list[Message], tools: list | None = None, reasoning_content: str | None = None, **kwargs) -> dict:
        """发送聊天请求，返回包含 content、tool_calls 和 reasoning_content 的字典。"""
        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }

        # 设置 provider 特定的认证
        if self.config.provider == "openai":
            request_kwargs["api_key"] = self.api_key
            if self.api_base:
                request_kwargs["api_base"] = self.api_base
        elif self.config.provider == "anthropic":
            request_kwargs["api_key"] = self.api_key
        elif self.config.provider == "google":
            request_kwargs["api_key"] = self.api_key
        else:
            request_kwargs["api_key"] = self.api_key
            if self.api_base:
                request_kwargs["base_url"] = self.api_base

        if tools:
            request_kwargs["tools"] = tools

        # 使用策略准备思考模式参数
        thinking_params = self.thinking_strategy.prepare_request(reasoning_content)
        if thinking_params:
            request_kwargs.update(thinking_params)

        request_kwargs.update({
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            **kwargs
        })

        response = await acompletion(**request_kwargs)
        choice = response.choices[0]
        message = choice.message

        # 使用策略提取思考内容
        reasoning = self.thinking_strategy.extract_reasoning_content(response)

        # 将 tool_calls 转换为 dict（litellm 返回的是对象）
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            tool_calls = [tc.to_dict() if hasattr(tc, 'to_dict') else tc for tc in tool_calls]

        return {
            "content": message.content or "",
            "tool_calls": tool_calls,
            "finish_reason": choice.finish_reason or "stop",
            "reasoning_content": reasoning,
            "should_store_reasoning": self.thinking_strategy.should_store_response(response),
        }