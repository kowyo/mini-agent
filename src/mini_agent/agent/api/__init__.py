from ...config import Provider
from .base import ApiBackend
from .message import AnthropicBackend
from .response import ResponsesBackend

_ANTHROPIC = AnthropicBackend()
_RESPONSES = ResponsesBackend()


def get_backend(provider: Provider) -> ApiBackend:
    if provider.api_type == "message":
        return _ANTHROPIC
    if provider.api_type == "response":
        return _RESPONSES
    raise ValueError(f"Unsupported api_type: {provider.api_type}")
