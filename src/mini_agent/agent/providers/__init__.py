from ...config import PROVIDERS, config
from .anthropic import AnthropicMessagesProvider
from .base import MessageStream, Provider
from .openai_responses import OpenAIResponsesProvider
from .types import (
    AssistantTurn,
    BlockStart,
    BlockStop,
    Message,
    StreamEvent,
    TextDelta,
    ThinkingDelta,
    ToolSpec,
)

_providers: dict[str, Provider] = {}


def get_provider() -> Provider:
    name = config.get_provider()
    provider = _providers.get(name)
    if provider is None:
        if name == "anthropic-messages":
            provider = AnthropicMessagesProvider()
        elif name == "openai-responses":
            provider = OpenAIResponsesProvider()
        else:
            raise ValueError(
                f"Unknown provider {name!r}; expected one of {', '.join(PROVIDERS)}."
            )
        _providers[name] = provider
    return provider


__all__ = [
    "AssistantTurn",
    "BlockStart",
    "BlockStop",
    "Message",
    "MessageStream",
    "Provider",
    "StreamEvent",
    "TextDelta",
    "ThinkingDelta",
    "ToolSpec",
    "get_provider",
]
