from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict

from ...cli.token import Usage


class TextBlock(TypedDict):
    type: Literal["text"]
    text: str


class ThinkingBlock(TypedDict):
    type: Literal["thinking"]
    thinking: str
    signature: NotRequired[str]
    encrypted_content: NotRequired[str]


class RedactedThinkingBlock(TypedDict):
    type: Literal["redacted_thinking"]
    data: str


class ToolCallBlock(TypedDict):
    type: Literal["tool_use"]
    id: str
    name: str
    input: dict[str, Any]


class ImageSource(TypedDict):
    type: Literal["base64"]
    media_type: str
    data: str


class ImageBlock(TypedDict):
    type: Literal["image"]
    source: ImageSource


class ToolResultBlock(TypedDict):
    type: Literal["tool_result"]
    tool_use_id: str
    content: str | list[TextBlock | ImageBlock]
    is_error: NotRequired[bool]


Block = (
    TextBlock
    | ThinkingBlock
    | RedactedThinkingBlock
    | ToolCallBlock
    | ImageBlock
    | ToolResultBlock
)


class Message(TypedDict):
    role: Literal["user", "assistant"]
    content: str | list[Block]


class ToolSpec(TypedDict):
    name: str
    description: str
    input_schema: dict[str, Any]


StopReason = Literal["tool_use", "end_turn"]


@dataclass(frozen=True)
class AssistantTurn:
    content: list[Block]
    stop_reason: StopReason
    usage: Usage

    @property
    def tool_calls(self) -> list[ToolCallBlock]:
        return [block for block in self.content if block["type"] == "tool_use"]


@dataclass(frozen=True)
class BlockStart:
    kind: Literal["text", "thinking"]


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ThinkingDelta:
    text: str


@dataclass(frozen=True)
class BlockStop:
    pass


StreamEvent = BlockStart | TextDelta | ThinkingDelta | BlockStop
