import json
import os
from collections.abc import Iterable, Iterator
from types import TracebackType
from typing import Any

from openai import OpenAI
from openai.lib.streaming.responses import ResponseStream, ResponseStreamManager
from openai.types.responses import (
    ResponseContentPartAddedEvent,
    ResponseContentPartDoneEvent,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseReasoningItem,
    ResponseReasoningSummaryPartAddedEvent,
    ResponseReasoningSummaryPartDoneEvent,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseReasoningTextDeltaEvent,
    ResponseReasoningTextDoneEvent,
    ResponseTextDeltaEvent,
    ResponseUsage,
)

from ...cli.token import Usage
from .base import MessageStream
from .types import (
    AssistantTurn,
    Block,
    BlockStart,
    BlockStop,
    ImageBlock,
    Message,
    StopReason,
    StreamEvent,
    TextBlock,
    TextDelta,
    ThinkingBlock,
    ThinkingDelta,
    ToolSpec,
)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL") or None,
        )
    return _client


REASONING_EFFORTS: tuple[str, ...] = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)


def _reasoning(effort: str) -> dict[str, str]:
    if effort not in REASONING_EFFORTS:
        raise ValueError(
            f"reasoning_effort {effort!r} is not supported by the "
            f"openai-responses provider; expected one of "
            f"{', '.join(REASONING_EFFORTS)}."
        )
    return {"effort": effort, "summary": "detailed"}


def _to_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
            "strict": False,
        }
        for tool in tools
    ]


def _data_url(block: ImageBlock) -> str:
    source = block["source"]
    return f"data:{source['media_type']};base64,{source['data']}"


def _tool_output(content: str | list[TextBlock | ImageBlock]) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(block["text"] for block in content if block["type"] == "text")


def _to_input_items(messages: list[Message]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages:
        content = message["content"]
        role = message["role"]
        if isinstance(content, str):
            items.append({"role": role, "content": content})
            continue

        parts: list[dict[str, Any]] = []
        for block in content:
            if block["type"] == "text":
                parts.append({"type": "input_text", "text": block["text"]})
            elif block["type"] == "image":
                if role == "user":
                    parts.append(
                        {
                            "type": "input_image",
                            "image_url": _data_url(block),
                            "detail": "auto",
                        }
                    )
            elif block["type"] == "tool_use":
                if parts:
                    items.append({"role": role, "content": parts})
                    parts = []
                items.append(
                    {
                        "type": "function_call",
                        "call_id": block["id"],
                        "name": block["name"],
                        "arguments": json.dumps(block["input"]),
                    }
                )
            elif block["type"] == "thinking":
                encrypted = block.get("encrypted_content")
                if encrypted:
                    if parts:
                        items.append({"role": role, "content": parts})
                        parts = []
                    items.append({"type": "reasoning", "encrypted_content": encrypted})
            elif block["type"] == "tool_result":
                if parts:
                    items.append({"role": role, "content": parts})
                    parts = []
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": block["tool_use_id"],
                        "output": _tool_output(block["content"]),
                    }
                )
        if len(parts) == 1 and parts[0]["type"] == "input_text":
            items.append({"role": role, "content": parts[0]["text"]})
        elif parts:
            items.append({"role": role, "content": parts})
    return items


def _parse_arguments(arguments: str) -> dict[str, Any]:
    if not arguments:
        return {}
    parsed = json.loads(arguments)
    return parsed if isinstance(parsed, dict) else {}


def _blocks_from_output(items: Iterable[object]) -> list[Block]:
    blocks: list[Block] = []
    for item in items:
        if isinstance(item, ResponseOutputMessage):
            for part in item.content:
                if isinstance(part, ResponseOutputText) and part.text:
                    blocks.append({"type": "text", "text": part.text})
        elif isinstance(item, ResponseFunctionToolCall):
            blocks.append(
                {
                    "type": "tool_use",
                    "id": item.call_id,
                    "name": item.name,
                    "input": _parse_arguments(item.arguments),
                }
            )
        elif isinstance(item, ResponseReasoningItem):
            text = "\n".join(
                [summary.text for summary in item.summary if summary.text]
                + [part.text for part in item.content or [] if part.text]
            )
            if text or item.encrypted_content:
                block: ThinkingBlock = {"type": "thinking", "thinking": text}
                if item.encrypted_content:
                    block["encrypted_content"] = item.encrypted_content
                blocks.append(block)
    return blocks


def _usage_from_response(usage: ResponseUsage | None) -> Usage:
    if usage is None:
        return Usage(
            input_tokens=0,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            output_tokens=0,
        )
    cached = usage.input_tokens_details.cached_tokens
    return Usage(
        input_tokens=max(usage.input_tokens - cached, 0),
        cache_creation_input_tokens=0,
        cache_read_input_tokens=cached,
        output_tokens=usage.output_tokens,
    )


def _events_from_response_stream(stream: Iterable[object]) -> Iterator[StreamEvent]:
    reasoning_text_open = False
    for event in stream:
        if isinstance(event, ResponseContentPartAddedEvent):
            if getattr(event.part, "type", None) == "output_text":
                yield BlockStart(kind="text")
        elif isinstance(event, ResponseTextDeltaEvent):
            yield TextDelta(text=event.delta)
        elif isinstance(event, ResponseContentPartDoneEvent):
            yield BlockStop()
        elif isinstance(event, ResponseReasoningSummaryPartAddedEvent):
            yield BlockStart(kind="thinking")
        elif isinstance(event, ResponseReasoningSummaryTextDeltaEvent):
            yield ThinkingDelta(text=event.delta)
        elif isinstance(event, ResponseReasoningSummaryPartDoneEvent):
            yield BlockStop()
        elif isinstance(event, ResponseReasoningTextDeltaEvent):
            if not reasoning_text_open:
                reasoning_text_open = True
                yield BlockStart(kind="thinking")
            yield ThinkingDelta(text=event.delta)
        elif isinstance(event, ResponseReasoningTextDoneEvent):
            reasoning_text_open = False
            yield BlockStop()


class _OpenAIStream:
    def __init__(self, manager: ResponseStreamManager) -> None:
        self._manager = manager
        self._stream: ResponseStream | None = None

    def __enter__(self) -> _OpenAIStream:
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
            raise RuntimeError("The response stream has not been entered.")
        return _events_from_response_stream(stream)

    def get_final_turn(self) -> AssistantTurn:
        stream = self._stream
        if stream is None:
            raise RuntimeError("The response stream has not been entered.")
        response = stream.get_final_response()
        content = _blocks_from_output(response.output)
        stop_reason: StopReason = (
            "tool_use"
            if any(block["type"] == "tool_use" for block in content)
            else "end_turn"
        )
        return AssistantTurn(
            content=content,
            stop_reason=stop_reason,
            usage=_usage_from_response(response.usage),
        )


class OpenAIResponsesProvider:
    effort_levels: tuple[str, ...] = REASONING_EFFORTS

    def stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        effort: str,
        cache_control: bool,
        max_tokens: int,
    ) -> MessageStream:
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": system,
            "input": _to_input_items(messages),
            "store": False,
            "reasoning": _reasoning(effort),
        }
        if tools:
            kwargs["tools"] = _to_tools(tools)
        return _OpenAIStream(_get_client().responses.stream(**kwargs))

    def list_models(self) -> list[str]:
        try:
            page = _get_client().models.list()
            model_ids = [model.id for model in page.data]
            while page.has_next_page():
                page = page.get_next_page()
                model_ids.extend(model.id for model in page.data)
            return sorted(model_ids)
        except Exception:
            return []
