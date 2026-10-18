from dataclasses import dataclass
from typing import Any, Literal, cast

from ..cli.token import Usage

ApiType = Literal["message", "response"]


@dataclass(frozen=True)
class TextBlock:
    text: str
    signature: str | None = None
    type: Literal["text"] = "text"


@dataclass(frozen=True)
class ThinkingBlock:
    thinking: str
    signature: str | None = None
    redacted: bool = False
    type: Literal["thinking"] = "thinking"


@dataclass(frozen=True)
class ImageBlock:
    data: str
    mime_type: str
    type: Literal["image"] = "image"


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    item_id: str | None = None
    namespace: str | None = None
    type: Literal["tool_call"] = "tool_call"


@dataclass(frozen=True)
class UserMessage:
    content: str | tuple[TextBlock | ImageBlock, ...]
    role: Literal["user"] = "user"


@dataclass(frozen=True)
class AssistantMessage:
    content: tuple[TextBlock | ThinkingBlock | ToolCall, ...]
    provider: str
    api_type: ApiType
    model: str
    usage: Usage
    stop_reason: str
    thinking_level: str | None = None
    role: Literal["assistant"] = "assistant"


@dataclass(frozen=True)
class ToolResultMessage:
    tool_call_id: str
    name: str
    content: tuple[TextBlock | ImageBlock, ...]
    is_error: bool = False
    role: Literal["tool_result"] = "tool_result"


Message = UserMessage | AssistantMessage | ToolResultMessage


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class Transcript:
    system: str
    tools: list[ToolSpec]
    messages: list[Message]


def usage_to_dict(usage: Usage) -> dict[str, int]:
    return {
        "input_tokens": usage.input_tokens,
        "cache_creation_input_tokens": usage.cache_creation_input_tokens,
        "cache_read_input_tokens": usage.cache_read_input_tokens,
        "output_tokens": usage.output_tokens,
    }


def usage_from_dict(data: dict[str, Any]) -> Usage:
    return Usage(
        input_tokens=int(data.get("input_tokens", 0)),
        cache_creation_input_tokens=int(data.get("cache_creation_input_tokens", 0)),
        cache_read_input_tokens=int(data.get("cache_read_input_tokens", 0)),
        output_tokens=int(data.get("output_tokens", 0)),
    )


def block_to_dict(
    block: TextBlock | ThinkingBlock | ImageBlock | ToolCall,
) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        result: dict[str, Any] = {"type": "text", "text": block.text}
        if block.signature is not None:
            result["signature"] = block.signature
        return result
    if isinstance(block, ThinkingBlock):
        result = {
            "type": "thinking",
            "thinking": block.thinking,
            "redacted": block.redacted,
        }
        if block.signature is not None:
            result["signature"] = block.signature
        return result
    if isinstance(block, ImageBlock):
        return {
            "type": "image",
            "data": block.data,
            "mime_type": block.mime_type,
        }
    result = {
        "type": "tool_call",
        "id": block.id,
        "name": block.name,
        "arguments": block.arguments,
    }
    if block.item_id is not None:
        result["item_id"] = block.item_id
    if block.namespace is not None:
        result["namespace"] = block.namespace
    return result


def block_from_dict(
    data: dict[str, Any],
) -> TextBlock | ThinkingBlock | ImageBlock | ToolCall:
    block_type = data.get("type")
    if block_type == "text":
        return TextBlock(
            text=str(data.get("text", "")),
            signature=data.get("signature"),
        )
    if block_type == "thinking":
        return ThinkingBlock(
            thinking=str(data.get("thinking", "")),
            signature=data.get("signature"),
            redacted=bool(data.get("redacted", False)),
        )
    if block_type == "image":
        source = data.get("source")
        if isinstance(source, dict):
            return ImageBlock(
                data=str(source.get("data", "")),
                mime_type=str(source.get("media_type", "image/png")),
            )
        return ImageBlock(
            data=str(data.get("data", "")),
            mime_type=str(data.get("mime_type", "image/png")),
        )
    if block_type == "tool_call":
        arguments = data.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        return ToolCall(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            arguments=arguments,
            item_id=data.get("item_id"),
            namespace=data.get("namespace"),
        )
    raise ValueError(f"Unknown content block type: {block_type}")


def message_to_dict(message: Message) -> dict[str, Any]:
    if isinstance(message, UserMessage):
        content = (
            message.content
            if isinstance(message.content, str)
            else [block_to_dict(block) for block in message.content]
        )
        return {"role": "user", "content": content}
    if isinstance(message, AssistantMessage):
        result: dict[str, Any] = {
            "role": "assistant",
            "content": [block_to_dict(block) for block in message.content],
            "provider": message.provider,
            "api_type": message.api_type,
            "model": message.model,
            "usage": usage_to_dict(message.usage),
            "stop_reason": message.stop_reason,
        }
        if message.thinking_level is not None:
            result["thinking_level"] = message.thinking_level
        return result
    return {
        "role": "tool_result",
        "tool_call_id": message.tool_call_id,
        "name": message.name,
        "content": [block_to_dict(block) for block in message.content],
        "is_error": message.is_error,
    }


def message_from_dict(data: dict[str, Any]) -> Message:
    role = data.get("role")
    if role == "user":
        content = data.get("content", "")
        if isinstance(content, str):
            return UserMessage(content=content)
        if not isinstance(content, list):
            raise ValueError("User content must be a string or a list")
        blocks = tuple(block_from_dict(block) for block in content)
        if not all(isinstance(block, TextBlock | ImageBlock) for block in blocks):
            raise ValueError("User content contains an unsupported block")
        return UserMessage(content=cast(tuple[TextBlock | ImageBlock, ...], blocks))
    if role == "assistant":
        content = data.get("content")
        if not isinstance(content, list):
            raise ValueError("Assistant content must be a list")
        blocks = tuple(block_from_dict(block) for block in content)
        if not all(
            isinstance(block, TextBlock | ThinkingBlock | ToolCall) for block in blocks
        ):
            raise ValueError("Assistant content contains an unsupported block")
        return AssistantMessage(
            content=cast(tuple[TextBlock | ThinkingBlock | ToolCall, ...], blocks),
            provider=str(data.get("provider", "")),
            api_type=data.get("api_type", "message"),
            model=str(data.get("model", "")),
            usage=usage_from_dict(data.get("usage") or {}),
            stop_reason=str(data.get("stop_reason", "end_turn")),
            thinking_level=data.get("thinking_level"),
        )
    if role == "tool_result":
        content = data.get("content")
        if not isinstance(content, list):
            raise ValueError("Tool result content must be a list")
        blocks = tuple(block_from_dict(block) for block in content)
        if not all(isinstance(block, TextBlock | ImageBlock) for block in blocks):
            raise ValueError("Tool result content contains an unsupported block")
        return ToolResultMessage(
            tool_call_id=str(data.get("tool_call_id", "")),
            name=str(data.get("name", "")),
            content=cast(tuple[TextBlock | ImageBlock, ...], blocks),
            is_error=bool(data.get("is_error", False)),
        )
    raise ValueError(f"Unknown message role: {role}")


def content_to_blocks(
    content: str | list[Any] | tuple[Any, ...],
) -> tuple[TextBlock | ImageBlock, ...]:
    if isinstance(content, str):
        return (TextBlock(text=content),)
    result: list[TextBlock | ImageBlock] = []
    for block in content:
        if isinstance(block, TextBlock | ImageBlock):
            result.append(block)
        elif isinstance(block, dict):
            converted = block_from_dict(block)
            if isinstance(converted, TextBlock | ImageBlock):
                result.append(converted)
        else:
            result.append(TextBlock(text=str(block)))
    return tuple(result)


def text_content(content: str | tuple[TextBlock | ImageBlock, ...]) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(block.text for block in content if isinstance(block, TextBlock))
