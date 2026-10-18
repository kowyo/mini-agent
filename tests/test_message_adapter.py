from collections.abc import Iterator

import pytest

from mini_agent.agent.api import message as message_api
from mini_agent.agent.api.base import TurnRequest
from mini_agent.agent.transcript import (
    AssistantMessage,
    TextBlock,
    ThinkingBlock,
    ToolCall,
    ToolResultMessage,
    Transcript,
    UserMessage,
)
from mini_agent.cli.token import Usage
from mini_agent.config import Provider


def request(
    messages: list,
    *,
    provider_id: str = "anthropic",
    model: str = "claude",
    effort: str = "high",
) -> TurnRequest:
    return TurnRequest(
        transcript=Transcript(system="system", tools=[], messages=messages),
        provider=Provider(
            id=provider_id,
            name="Anthropic",
            base_url="https://example.com",
            api_key_env="KEY",
        ),
        model=model,
        reasoning_effort=effort,
        session_id="session",
        max_output_tokens=1024,
    )


def assistant(
    *,
    provider: str = "anthropic",
    api_type: str = "message",
    model: str = "claude",
    content: tuple = (),
) -> AssistantMessage:
    return AssistantMessage(
        content=content,
        provider=provider,
        api_type=api_type,
        model=model,
        usage=Usage(1, 0, 0, 1),
        stop_reason="end_turn",
    )


def convert(messages: list, *, effort: str = "high") -> list[dict]:
    req = request(messages, effort=effort)
    return message_api._convert_messages(
        req.transcript.messages,
        provider_id=req.provider.id,
        model=req.model,
        thinking_enabled=req.reasoning_effort != "disabled",
    )


def test_same_model_thinking_is_replayed() -> None:
    converted = convert(
        [
            UserMessage(content="question"),
            assistant(
                content=(
                    ThinkingBlock(thinking="why", signature="sig"),
                    TextBlock(text="answer"),
                )
            ),
        ]
    )

    assert converted[1]["content"][0] == {
        "type": "thinking",
        "thinking": "why",
        "signature": "sig",
    }


def test_foreign_thinking_is_dropped() -> None:
    converted = convert(
        [
            UserMessage(content="question"),
            assistant(
                provider="openai",
                api_type="response",
                model="gpt",
                content=(
                    ThinkingBlock(thinking="why", signature="sig"),
                    TextBlock(text="answer"),
                ),
            ),
        ]
    )

    assert converted[1]["content"] == [{"type": "text", "text": "answer"}]


def test_thinking_is_dropped_when_disabled() -> None:
    converted = convert(
        [
            UserMessage(content="question"),
            assistant(
                content=(
                    ThinkingBlock(thinking="why", signature="sig"),
                    TextBlock(text="answer"),
                )
            ),
        ],
        effort="disabled",
    )

    assert converted[1]["content"] == [{"type": "text", "text": "answer"}]


def test_redacted_thinking_is_replayed() -> None:
    converted = convert(
        [
            UserMessage(content="question"),
            assistant(
                content=(
                    ThinkingBlock(
                        thinking="[Reasoning redacted]",
                        signature="opaque",
                        redacted=True,
                    ),
                )
            ),
        ]
    )

    assert converted[1]["content"] == [{"type": "redacted_thinking", "data": "opaque"}]


def test_tool_ids_are_normalized_for_foreign_messages() -> None:
    weird = "call|with/slash-and-a-very-long-suffix-" + "x" * 80
    converted = convert(
        [
            UserMessage(content="question"),
            assistant(
                provider="openai",
                api_type="response",
                model="gpt",
                content=(ToolCall(id=weird, name="bash", arguments={"command": "ls"}),),
            ),
            ToolResultMessage(
                tool_call_id=weird,
                name="bash",
                content=(TextBlock(text="ok"),),
            ),
        ]
    )

    tool_use_id = converted[1]["content"][0]["id"]
    assert tool_use_id != weird
    assert len(tool_use_id) <= 64
    assert converted[2]["content"][0]["tool_use_id"] == tool_use_id


def test_consecutive_tool_results_are_grouped() -> None:
    messages = [
        UserMessage(content="question"),
        assistant(
            content=(
                ToolCall(id="a", name="one", arguments={}),
                ToolCall(id="b", name="two", arguments={}),
            )
        ),
        ToolResultMessage(tool_call_id="a", name="one", content=(TextBlock(text="a"),)),
        ToolResultMessage(tool_call_id="b", name="two", content=(TextBlock(text="b"),)),
    ]

    converted = convert(messages)

    assert len(converted) == 3
    assert [block["type"] for block in converted[2]["content"]] == [
        "tool_result",
        "tool_result",
    ]


def test_orphaned_tool_calls_get_a_synthetic_result() -> None:
    converted = convert(
        [
            UserMessage(content="question"),
            assistant(content=(ToolCall(id="call", name="bash", arguments={}),)),
            UserMessage(content="next"),
        ]
    )

    tool_result = converted[2]["content"][0]
    assert tool_result["tool_use_id"] == "call"
    assert tool_result["is_error"] is True
    assert tool_result["content"] == "No result provided"


class FakeStream:
    def __iter__(self) -> Iterator[object]:
        return iter(())

    def get_final_message(self) -> object:
        raise AssertionError("not used")


class FakeManager:
    def __init__(self) -> None:
        self.stream = FakeStream()

    def __enter__(self) -> FakeStream:
        return self.stream

    def __exit__(self, *args: object) -> None:
        pass


def test_anthropic_request_always_enables_cache_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeMessages:
        def stream(self, **kwargs: object) -> FakeManager:
            captured.update(kwargs)
            return FakeManager()

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setattr(message_api, "get_client", lambda: FakeClient())
    req = request([UserMessage(content="question")])

    with message_api.AnthropicBackend().run_turn(req):
        pass

    assert captured["cache_control"] == {"type": "ephemeral"}
    assert captured["max_tokens"] == 1024
    assert captured["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert captured["output_config"] == {"effort": "high"}
