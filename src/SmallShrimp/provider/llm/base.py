from dataclasses import dataclass
from typing import Any

import yaml
from litellm import acompletion
from litellm.types.completion import ChatCompletionMessageParam as Message

@dataclass
class LLMConfig:
    provider: str
    model: str
    api_key: str
    api_base: str | None = None
    temperature: float = 0.7

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

      @classmethod
      def from_config(cls, config: LLMConfig) -> "LLMProvider":
          return cls(config)

      async def chat(
          self,
          messages: list[Message],
          **kwargs: Any,
      ) -> str:
          request_kwargs: dict[str, Any] = {
              "model": self.model,
              "messages": messages,
          }

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

          request_kwargs.update(kwargs)

          response = await acompletion(**request_kwargs)
          choice = response.choices[0]
          return choice.message.content or ""