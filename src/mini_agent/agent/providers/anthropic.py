import hashlib
import json
import os
import re
import urllib.request
from collections.abc import Iterable, Iterator
from types import TracebackType
from typing import Any
from urllib.parse import urlparse

from anthropic import Anthropic
from anthropic.lib.streaming import ContentBlockStopEvent, MessageStreamManager
from anthropic.lib.streaming import MessageStream as AnthropicMessageStream
from anthropic.types import (
    ContentBlock,
    Message,
    RawContentBlockDeltaEvent,
    RawContentBlockStartEvent,
    RedactedThinkingBlock,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)
from anthropic.types import (
    TextDelta as AnthropicTextDelta,
)
from anthropic.types import (
    ThinkingDelta as AnthropicThinkingDelta,
)

from ...cli.token import Usage
from .base import MessageStream
from .types import (
    AssistantTurn,
    Block,
    BlockStart,
    BlockStop,
    StopReason,
    StreamEvent,
    TextDelta,
    ThinkingDelta,
    ToolSpec,
)
from .types import (
    Message as NeutralMessage,
)
from .types import (
    ThinkingBlock as NeutralThinkingBlock,
)
from .types import (
    ToolResultBlock as NeutralToolResultBlock,
)

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        if os.getenv("ANTHROPIC_API_KEY"):
            os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
        _client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
    return _client


def _thinking_params(
    effort: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if effort == "disabled":
        return None, None
    thinking: dict[str, Any] = {"type": "adaptive", "display": "summarized"}
    if effort == "adaptive":
        return thinking, None
    return thinking, {"effort": effort}


def _block_to_neutral(block: ContentBlock) -> Block | None:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ThinkingBlock):
        thinking: NeutralThinkingBlock = {
            "type": "thinking",
            "thinking": block.thinking,
        }
        if block.signature:
            thinking["signature"] = block.signature
        return thinking
    if isinstance(block, RedactedThinkingBlock):
        return {"type": "redacted_thinking", "data": block.data}
    if isinstance(block, ToolUseBlock):
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    return None


_SAFE_TOOL_ID = re.compile(r"[a-zA-Z0-9_-]{1,64}")


def _safe_tool_id(tool_id: str) -> str:
    if _SAFE_TOOL_ID.fullmatch(tool_id):
        return tool_id
    return hashlib.sha256(tool_id.encode()).hexdigest()


def _is_same_source(message: NeutralMessage, model: str) -> bool:
    return (
        message.get("provider") == "anthropic-messages"
        and message.get("model") == model
    )


def _to_message_params(
    messages: list[NeutralMessage], model: str
) -> list[NeutralMessage]:
    cleaned: list[NeutralMessage] = []
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            cleaned.append(message)
            continue
        same_source = _is_same_source(message, model)
        blocks: list[Block] = []
        for block in content:
            if block["type"] == "thinking":
                signature = block.get("signature")
                if same_source and signature:
                    blocks.append(
                        {
                            "type": "thinking",
                            "thinking": block["thinking"],
                            "signature": signature,
                        }
                    )
                elif not same_source and block["thinking"]:
                    blocks.append({"type": "text", "text": block["thinking"]})
            elif block["type"] == "redacted_thinking":
                if same_source:
                    blocks.append(block)
            elif block["type"] == "tool_use":
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": _safe_tool_id(block["id"]),
                        "name": block["name"],
                        "input": block["input"],
                    }
                )
            elif block["type"] == "tool_result":
                result: NeutralToolResultBlock = {
                    "type": "tool_result",
                    "tool_use_id": _safe_tool_id(block["tool_use_id"]),
                    "content": block["content"],
                }
                if "is_error" in block:
                    result["is_error"] = block["is_error"]
                blocks.append(result)
            else:
                blocks.append(block)
        cleaned.append({"role": message["role"], "content": blocks})
    return cleaned


def _usage_from_message(message: Message) -> Usage:
    usage = message.usage
    return Usage(
        input_tokens=usage.input_tokens,
        cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
        cache_read_input_tokens=usage.cache_read_input_tokens or 0,
        output_tokens=usage.output_tokens,
    )


def _events_from_message_stream(stream: Iterable[object]) -> Iterator[StreamEvent]:
    for event in stream:
        if isinstance(event, RawContentBlockStartEvent):
            block_type = event.content_block.type
            if block_type == "text":
                yield BlockStart(kind="text")
            elif block_type == "thinking":
                yield BlockStart(kind="thinking")
        elif isinstance(event, RawContentBlockDeltaEvent):
            delta = event.delta
            if isinstance(delta, AnthropicTextDelta):
                yield TextDelta(text=delta.text)
            elif isinstance(delta, AnthropicThinkingDelta):
                yield ThinkingDelta(text=delta.thinking)
        elif isinstance(event, ContentBlockStopEvent):
            yield BlockStop()


class _AnthropicStream:
    def __init__(self, manager: MessageStreamManager) -> None:
        self._manager = manager
        self._stream: AnthropicMessageStream | None = None

    def __enter__(self) -> _AnthropicStream:
        self._stream = self._manager.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._manager.__exit__(exc_type, exc, tb)

    def __iter__(self) -> Iterator[StreamEvent]:
        stream = self._stream
        if stream is None:
            raise RuntimeError("The message stream has not been entered.")
        return _events_from_message_stream(iter(stream))

    def get_final_turn(self) -> AssistantTurn:
        stream = self._stream
        if stream is None:
            raise RuntimeError("The message stream has not been entered.")
        message = stream.get_final_message()
        content = [
            block
            for block in (_block_to_neutral(block) for block in message.content)
            if block is not None
        ]
        stop_reason: StopReason = (
            "tool_use" if message.stop_reason == "tool_use" else "end_turn"
        )
        return AssistantTurn(
            content=content,
            stop_reason=stop_reason,
            usage=_usage_from_message(message),
        )


class AnthropicMessagesProvider:
    name = "anthropic-messages"
    effort_levels: tuple[str, ...] = (
        "disabled",
        "adaptive",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    )

    def stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[NeutralMessage],
        tools: list[ToolSpec],
        effort: str,
        cache_control: bool,
        max_tokens: int,
    ) -> MessageStream:
        thinking, output_config = _thinking_params(effort)
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": _to_message_params(messages, model),
            "tools": tools,
        }
        if cache_control:
            kwargs["cache_control"] = {"type": "ephemeral"}
        if thinking is not None:
            kwargs["thinking"] = thinking
            if output_config is not None:
                kwargs["output_config"] = output_config
        return _AnthropicStream(_get_client().messages.stream(**kwargs))

    def list_models(self) -> list[str]:
        try:
            return self._list_models_sdk()
        except Exception:
            pass
        try:
            return self._list_models_manual()
        except Exception:
            return []

    @staticmethod
    def _list_models_sdk() -> list[str]:
        client = _get_client()
        model_ids: list[str] = []
        page = client.models.list(limit=100)
        model_ids.extend(model.id for model in page.data)
        while page.has_more:
            page = page.get_next_page()
            model_ids.extend(model.id for model in page.data)
        return sorted(model_ids)

    @staticmethod
    def _list_models_manual() -> list[str]:
        client = _get_client()
        parsed = urlparse(str(client.base_url))
        url = f"{parsed.scheme}://{parsed.netloc}/v1/models"

        headers: dict[str, str] = {"anthropic-version": "2023-06-01"}
        if client.auth_token:
            headers["Authorization"] = f"Bearer {client.auth_token}"
        elif client.api_key:
            headers["x-api-key"] = client.api_key

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        return sorted(model["id"] for model in data.get("data", []))
