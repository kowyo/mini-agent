from collections.abc import Iterator
from typing import cast

from anthropic.lib.streaming import (
    ContentBlockStopEvent,
    MessageStream,
    MessageStreamEvent,
    MessageStreamManager,
)
from anthropic.types import (
    Message,
    RawContentBlockDeltaEvent,
    RawContentBlockStartEvent,
    RedactedThinkingBlock,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    Usage,
)
from anthropic.types import (
    TextDelta as AnthropicTextDelta,
)
from anthropic.types import (
    ThinkingDelta as AnthropicThinkingDelta,
)

from mini_agent.agent.providers import anthropic
from mini_agent.agent.providers.types import (
    BlockStart,
    BlockStop,
    TextDelta,
    ThinkingDelta,
)
from mini_agent.agent.providers.types import (
    Message as NeutralMessage,
)


class _Stream:
    def __init__(self, events: list[MessageStreamEvent], message: Message) -> None:
        self._events = events
        self._message = message

    def __iter__(self) -> Iterator[MessageStreamEvent]:
        return iter(self._events)

    def get_final_message(self) -> Message:
        return self._message


class _Manager:
    def __init__(self, stream: _Stream) -> None:
        self._stream = stream

    def __enter__(self) -> _Stream:
        return self._stream

    def __exit__(self, *args: object) -> None:
        return None


def _wrap(stream: _Stream) -> anthropic._AnthropicStream:
    manager = cast("MessageStreamManager[MessageStream]", _Manager(stream))
    return anthropic._AnthropicStream(manager)


def _usage(
    input_tokens: int = 1,
    output_tokens: int = 1,
    cache_creation: int | None = 0,
    cache_read: int | None = 0,
) -> Usage:
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation,
        cache_read_input_tokens=cache_read,
    )


def test_thinking_params_follow_effort_setting() -> None:
    assert anthropic._thinking_params("disabled") == (None, None)
    assert anthropic._thinking_params("adaptive") == (
        {"type": "adaptive", "display": "summarized"},
        None,
    )
    assert anthropic._thinking_params("high") == (
        {"type": "adaptive", "display": "summarized"},
        {"effort": "high"},
    )


def test_stream_events_are_mapped_to_neutral_events() -> None:
    events: list[MessageStreamEvent] = [
        RawContentBlockStartEvent(
            type="content_block_start",
            index=0,
            content_block=TextBlock(type="text", text=""),
        ),
        RawContentBlockDeltaEvent(
            type="content_block_delta",
            index=0,
            delta=AnthropicTextDelta(type="text_delta", text="hello"),
        ),
        ContentBlockStopEvent(
            type="content_block_stop",
            index=0,
            content_block=TextBlock(type="text", text=""),
        ),
        RawContentBlockStartEvent(
            type="content_block_start",
            index=1,
            content_block=ThinkingBlock(type="thinking", thinking="", signature="sig"),
        ),
        RawContentBlockDeltaEvent(
            type="content_block_delta",
            index=1,
            delta=AnthropicThinkingDelta(type="thinking_delta", thinking="hmm"),
        ),
        ContentBlockStopEvent(
            type="content_block_stop",
            index=1,
            content_block=ThinkingBlock(type="thinking", thinking="", signature="sig"),
        ),
    ]

    mapped = list(anthropic._events_from_message_stream(iter(events)))

    assert mapped == [
        BlockStart(kind="text"),
        TextDelta(text="hello"),
        BlockStop(),
        BlockStart(kind="thinking"),
        ThinkingDelta(text="hmm"),
        BlockStop(),
    ]


def test_final_turn_converts_anthropic_blocks_and_usage() -> None:
    message = Message(
        id="msg-1",
        content=[
            ThinkingBlock(type="thinking", thinking="reasoning", signature="sig"),
            RedactedThinkingBlock(type="redacted_thinking", data="opaque"),
            TextBlock(type="text", text="answer"),
            ToolUseBlock(
                type="tool_use", id="tool-1", name="bash", input={"command": "ls"}
            ),
        ],
        model="claude-sonnet-4-6",
        role="assistant",
        type="message",
        stop_reason="tool_use",
        usage=_usage(input_tokens=10, output_tokens=2, cache_creation=3, cache_read=4),
    )

    with _wrap(_Stream([], message)) as stream:
        turn = stream.get_final_turn()

    assert turn.content == [
        {"type": "thinking", "thinking": "reasoning", "signature": "sig"},
        {"type": "redacted_thinking", "data": "opaque"},
        {"type": "text", "text": "answer"},
        {
            "type": "tool_use",
            "id": "tool-1",
            "name": "bash",
            "input": {"command": "ls"},
        },
    ]
    assert turn.stop_reason == "tool_use"
    assert turn.usage.input_tokens == 10
    assert turn.usage.cache_creation_input_tokens == 3
    assert turn.usage.cache_read_input_tokens == 4
    assert turn.usage.output_tokens == 2


def test_final_turn_without_tool_use_ends_the_turn() -> None:
    message = Message(
        id="msg-2",
        content=[TextBlock(type="text", text="done")],
        model="claude-sonnet-4-6",
        role="assistant",
        type="message",
        stop_reason="end_turn",
        usage=_usage(),
    )

    with _wrap(_Stream([], message)) as stream:
        turn = stream.get_final_turn()

    assert turn.stop_reason == "end_turn"
    assert turn.tool_calls == []


def test_message_params_replay_signed_thinking_for_same_source() -> None:
    messages: list[NeutralMessage] = [
        {
            "role": "assistant",
            "provider": "anthropic-messages",
            "model": "claude",
            "content": [
                {
                    "type": "thinking",
                    "thinking": "t",
                    "signature": "sig",
                    "encrypted_content": "enc",
                }
            ],
        }
    ]

    assert anthropic._to_message_params(messages, "claude") == [
        {
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": "t", "signature": "sig"}],
        }
    ]


def test_message_params_downgrade_foreign_thinking_to_text() -> None:
    messages: list[NeutralMessage] = [
        {
            "role": "assistant",
            "provider": "openai-responses",
            "model": "gpt",
            "content": [
                {"type": "thinking", "thinking": "foreign", "encrypted_content": "enc"},
                {"type": "text", "text": "answer"},
            ],
        }
    ]

    assert anthropic._to_message_params(messages, "claude") == [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "foreign"},
                {"type": "text", "text": "answer"},
            ],
        }
    ]


def test_message_params_drop_foreign_redacted_thinking() -> None:
    messages: list[NeutralMessage] = [
        {
            "role": "assistant",
            "provider": "openai-responses",
            "model": "gpt",
            "content": [
                {"type": "redacted_thinking", "data": "opaque"},
                {"type": "text", "text": "answer"},
            ],
        }
    ]

    assert anthropic._to_message_params(messages, "claude") == [
        {"role": "assistant", "content": [{"type": "text", "text": "answer"}]}
    ]
