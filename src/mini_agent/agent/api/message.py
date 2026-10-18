from collections.abc import Iterator
from typing import Any, cast

import anthropic.lib.streaming
from anthropic.types import (
    ImageBlockParam,
    Message,
    MessageParam,
    RedactedThinkingBlock,
    TextBlockParam,
    TextDelta,
    ThinkingDelta,
    ToolParam,
    ToolResultBlockParam,
    ToolUseBlock,
)
from anthropic.types import (
    TextBlock as AnthropicTextBlock,
)
from anthropic.types import (
    ThinkingBlock as AnthropicThinkingBlock,
)

from ...cli.token import Usage
from ...config import get_client
from ..transcript import (
    AssistantMessage,
    ImageBlock,
    TextBlock,
    ThinkingBlock,
    ToolCall,
    ToolResultMessage,
    ToolSpec,
    UserMessage,
)
from ..transcript import (
    Message as TranscriptMessage,
)
from .base import (
    ApiBackend,
    BlockEnd,
    StreamEvent,
    TurnRequest,
    TurnStream,
)
from .base import (
    TextDelta as NeutralTextDelta,
)
from .base import (
    ThinkingDelta as NeutralThinkingDelta,
)
from .ids import normalize_foreign_tool_ids


def _thinking_params(
    effort: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if effort == "disabled":
        return None, None
    thinking: dict[str, Any] = {"type": "adaptive", "display": "summarized"}
    if effort == "adaptive":
        return thinking, None
    return thinking, {"effort": effort}


def _tool_result_content(
    message: ToolResultMessage,
) -> str | list[TextBlockParam | ImageBlockParam]:
    if message.is_error:
        texts = [
            block.text for block in message.content if isinstance(block, TextBlock)
        ]
        return "\n".join(texts) if texts else "Error"
    blocks: list[TextBlockParam | ImageBlockParam] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            blocks.append({"type": "text", "text": block.text})
        elif isinstance(block, ImageBlock):
            blocks.append(
                cast(
                    ImageBlockParam,
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": block.mime_type,
                            "data": block.data,
                        },
                    },
                )
            )
    if not blocks:
        return "(no content)"
    if all(block["type"] == "text" for block in blocks):
        return "\n".join(cast(TextBlockParam, block)["text"] for block in blocks)
    return blocks


def _assistant_content(
    message: AssistantMessage,
    *,
    provider_id: str,
    model: str,
    thinking_enabled: bool,
    tool_ids: dict[str, str],
) -> list[dict[str, Any]]:
    same_model = (
        message.provider == provider_id
        and message.api_type == "message"
        and message.model == model
    )
    content: list[dict[str, Any]] = []
    for block in message.content:
        if isinstance(block, ThinkingBlock):
            if not same_model or not thinking_enabled or not block.signature:
                continue
            if block.redacted:
                content.append({"type": "redacted_thinking", "data": block.signature})
            else:
                content.append(
                    {
                        "type": "thinking",
                        "thinking": block.thinking,
                        "signature": block.signature,
                    }
                )
        elif isinstance(block, TextBlock):
            content.append({"type": "text", "text": block.text})
        elif isinstance(block, ToolCall):
            content.append(
                {
                    "type": "tool_use",
                    "id": tool_ids.get(block.id, block.id),
                    "name": block.name,
                    "input": block.arguments,
                }
            )
    return content


def _user_content(
    message: UserMessage,
) -> str | list[TextBlockParam | ImageBlockParam]:
    if isinstance(message.content, str):
        return message.content
    blocks: list[TextBlockParam | ImageBlockParam] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            blocks.append({"type": "text", "text": block.text})
        elif isinstance(block, ImageBlock):
            blocks.append(
                cast(
                    ImageBlockParam,
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": block.mime_type,
                            "data": block.data,
                        },
                    },
                )
            )
    return blocks


def _synthetic_results(
    call: ToolCall,
    pending: dict[str, ToolResultMessage],
) -> ToolResultMessage:
    return pending.get(
        call.id,
        ToolResultMessage(
            tool_call_id=call.id,
            name=call.name,
            content=(TextBlock(text="No result provided"),),
            is_error=True,
        ),
    )


def _convert_messages(
    messages: list[TranscriptMessage],
    *,
    provider_id: str,
    model: str,
    thinking_enabled: bool,
) -> list[MessageParam]:
    tool_ids = normalize_foreign_tool_ids(
        messages,
        provider_id=provider_id,
        api_type="message",
        model=model,
    )
    converted: list[MessageParam] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if isinstance(message, UserMessage):
            converted.append({"role": "user", "content": _user_content(message)})
            index += 1
            continue

        if isinstance(message, AssistantMessage):
            if message.stop_reason in {"error", "aborted"}:
                index += 1
                continue
            calls = [block for block in message.content if isinstance(block, ToolCall)]
            content = _assistant_content(
                message,
                provider_id=provider_id,
                model=model,
                thinking_enabled=thinking_enabled,
                tool_ids=tool_ids,
            )
            if content:
                converted.append(
                    cast(
                        MessageParam,
                        {"role": "assistant", "content": content},
                    )
                )

            results: dict[str, ToolResultMessage] = {}
            cursor = index + 1
            while cursor < len(messages) and isinstance(
                messages[cursor], ToolResultMessage
            ):
                tool_result = cast(ToolResultMessage, messages[cursor])
                results[tool_result.tool_call_id] = tool_result
                cursor += 1

            if calls:
                result_blocks: list[ToolResultBlockParam] = []
                error_images: list[ImageBlockParam] = []
                for call in calls:
                    tool_result = _synthetic_results(call, results)
                    result_blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_ids.get(call.id, call.id),
                            "content": _tool_result_content(tool_result),
                            "is_error": tool_result.is_error,
                        }
                    )
                    if tool_result.is_error:
                        error_images.extend(
                            cast(
                                ImageBlockParam,
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": block.mime_type,
                                        "data": block.data,
                                    },
                                },
                            )
                            for block in tool_result.content
                            if isinstance(block, ImageBlock)
                        )
                converted.append(
                    {
                        "role": "user",
                        "content": [*result_blocks, *error_images],
                    }
                )
            index = cursor
            continue

        if isinstance(message, ToolResultMessage):
            converted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_ids.get(
                                message.tool_call_id, message.tool_call_id
                            ),
                            "content": _tool_result_content(message),
                            "is_error": message.is_error,
                        }
                    ],
                }
            )
            index += 1
            continue

        index += 1
    return converted


def _tools(tools: list[ToolSpec]) -> list[ToolParam]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.parameters,
        }
        for tool in tools
    ]


def _usage(usage: object) -> Usage:
    value = cast(Any, usage)
    return Usage(
        input_tokens=value.input_tokens,
        cache_creation_input_tokens=getattr(value, "cache_creation_input_tokens", 0)
        or 0,
        cache_read_input_tokens=getattr(value, "cache_read_input_tokens", 0) or 0,
        output_tokens=value.output_tokens,
    )


def _assistant_message(
    response: Message,
    request: TurnRequest,
) -> AssistantMessage:
    content: list[TextBlock | ThinkingBlock | ToolCall] = []
    for block in response.content:
        if isinstance(block, AnthropicTextBlock):
            content.append(TextBlock(text=block.text))
        elif isinstance(block, AnthropicThinkingBlock):
            content.append(
                ThinkingBlock(
                    thinking=block.thinking,
                    signature=block.signature,
                )
            )
        elif isinstance(block, RedactedThinkingBlock):
            content.append(
                ThinkingBlock(
                    thinking="[Reasoning redacted]",
                    signature=block.data,
                    redacted=True,
                )
            )
        elif isinstance(block, ToolUseBlock):
            content.append(
                ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
                )
            )
    return AssistantMessage(
        content=tuple(content),
        provider=request.provider.id,
        api_type="message",
        model=request.model,
        usage=_usage(response.usage),
        stop_reason=response.stop_reason or "end_turn",
        thinking_level=request.reasoning_effort,
    )


class _AnthropicTurnStream(TurnStream):
    def __init__(self, request: TurnRequest) -> None:
        self._request = request
        self._manager: Any = None
        self._stream: anthropic.lib.streaming.MessageStream | None = None

    def __enter__(self) -> _AnthropicTurnStream:
        thinking, output_config = _thinking_params(self._request.reasoning_effort)
        kwargs: dict[str, Any] = {
            "model": self._request.model,
            "max_tokens": self._request.max_output_tokens or 32768,
            "system": self._request.transcript.system,
            "messages": _convert_messages(
                self._request.transcript.messages,
                provider_id=self._request.provider.id,
                model=self._request.model,
                thinking_enabled=self._request.reasoning_effort != "disabled",
            ),
            "tools": _tools(self._request.transcript.tools),
            "cache_control": {"type": "ephemeral"},
        }
        if thinking is not None:
            kwargs["thinking"] = thinking
        if output_config is not None:
            kwargs["output_config"] = output_config
        self._manager = get_client().messages.stream(**kwargs)
        self._stream = self._manager.__enter__()
        return self

    def __exit__(self, *args: object) -> None:
        if self._manager is not None:
            self._manager.__exit__(*args)

    def __iter__(self) -> Iterator[StreamEvent]:
        if self._stream is None:
            return
        for event in self._stream:
            if event.type == "content_block_delta":
                delta = event.delta
                if isinstance(delta, TextDelta):
                    yield NeutralTextDelta(delta.text)
                elif isinstance(delta, ThinkingDelta):
                    yield NeutralThinkingDelta(delta.thinking)
            elif event.type == "content_block_stop":
                yield BlockEnd()

    def get_final_message(self) -> AssistantMessage:
        if self._stream is None:
            raise RuntimeError("Stream was not opened")
        return _assistant_message(self._stream.get_final_message(), self._request)


class AnthropicBackend(ApiBackend):
    def run_turn(self, request: TurnRequest) -> TurnStream:
        return _AnthropicTurnStream(request)
