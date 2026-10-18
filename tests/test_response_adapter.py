import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from mini_agent.agent.api import response as response_api
from mini_agent.agent.api.base import TurnRequest
from mini_agent.agent.transcript import (
    AssistantMessage,
    ImageBlock,
    TextBlock,
    ThinkingBlock,
    ToolCall,
    ToolResultMessage,
    Transcript,
    UserMessage,
)
from mini_agent.cli import models
from mini_agent.cli.token import Usage
from mini_agent.config import Provider


def request(messages: list[Any], *, model: str = "gpt-5.4") -> TurnRequest:
    return TurnRequest(
        transcript=Transcript(system="system", tools=[], messages=messages),
        provider=Provider(
            id="openai",
            name="OpenAI",
            base_url="https://api.openai.com/v1",
            api_key_env="OPENAI_API_KEY",
            api_type="response",
        ),
        model=model,
        reasoning_effort="high",
        session_id="session",
        max_output_tokens=1024,
    )


def assistant(
    *,
    provider: str = "openai",
    api_type: str = "response",
    model: str = "gpt-5.4",
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


def convert(
    messages: list[Any], *, model: str = "gpt-5.4", thinking: bool = True
) -> list[dict[str, Any]]:
    return response_api._convert_input(
        messages,
        provider_id="openai",
        model=model,
        thinking_enabled=thinking,
    )


def test_same_model_reasoning_and_message_ids_are_replayed() -> None:
    signature = json.dumps({"id": "rs_1", "type": "reasoning"})
    text_signature = json.dumps({"id": "msg_1", "phase": "final_answer"})
    converted = convert(
        [
            UserMessage(content="question"),
            assistant(
                content=(
                    ThinkingBlock(thinking="why", signature=signature),
                    TextBlock(text="answer", signature=text_signature),
                )
            ),
        ]
    )

    assert converted[1] == {"id": "rs_1", "type": "reasoning"}
    assert converted[2]["id"] == "msg_1"
    assert converted[2]["phase"] == "final_answer"
    assert converted[2]["content"][0]["text"] == "answer"


def test_foreign_thinking_is_dropped_and_item_ids_are_omitted() -> None:
    converted = convert(
        [
            UserMessage(content="question"),
            assistant(
                content=(
                    ThinkingBlock(thinking="why", signature='{"id":"rs_1"}'),
                    TextBlock(text="answer", signature='{"id":"msg_1"}'),
                    ToolCall(
                        id="call_1",
                        name="bash",
                        arguments={"command": "ls"},
                        item_id="fc_1",
                        namespace="functions",
                    ),
                )
            ),
        ],
        model="gpt-5.5",
    )

    assert converted[1] == {"role": "assistant", "content": "answer"}
    function_call = converted[2]
    assert function_call["type"] == "function_call"
    assert "id" not in function_call
    assert "namespace" not in function_call


def test_tool_result_output_preserves_text_and_images() -> None:
    converted = convert(
        [
            ToolResultMessage(
                tool_call_id="call_1",
                name="read_file",
                content=(
                    TextBlock(text="image"),
                    ImageBlock(data="aGk=", mime_type="image/png"),
                ),
            )
        ]
    )

    assert converted[0]["type"] == "function_call_output"
    assert converted[0]["output"] == [
        {"type": "input_text", "text": "image"},
        {
            "type": "input_image",
            "detail": "auto",
            "image_url": "data:image/png;base64,aGk=",
        },
    ]


def test_error_tool_output_is_prefixed() -> None:
    converted = convert(
        [
            ToolResultMessage(
                tool_call_id="call_1",
                name="bash",
                content=(TextBlock(text="bad"),),
                is_error=True,
            )
        ]
    )

    assert converted[0]["output"] == "Error: bad"


def test_usage_maps_cached_tokens() -> None:
    usage = SimpleNamespace(
        input_tokens=10,
        input_tokens_details=SimpleNamespace(cached_tokens=2),
        output_tokens=5,
    )

    assert response_api._usage(usage) == Usage(8, 0, 2, 5)


def test_assistant_message_converts_output_items() -> None:
    response = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="message",
                id="msg_1",
                phase="final_answer",
                content=[
                    SimpleNamespace(type="output_text", text="answer"),
                ],
            ),
            SimpleNamespace(
                type="function_call",
                call_id="call_1",
                id="fc_1",
                name="bash",
                arguments='{"command":"ls"}',
                namespace="functions",
            ),
        ],
        usage=SimpleNamespace(
            input_tokens=10,
            input_tokens_details=SimpleNamespace(cached_tokens=0),
            output_tokens=5,
        ),
    )

    message = response_api._assistant_message(response, request([]))

    assert isinstance(message.content[0], TextBlock)
    assert message.content[0].signature == '{"id":"msg_1","phase":"final_answer"}'
    assert isinstance(message.content[1], ToolCall)
    assert message.content[1].item_id == "fc_1"
    assert message.content[1].arguments == {"command": "ls"}
    assert message.stop_reason == "tool_use"


def test_reasoning_config_uses_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(models, "get_model_reasoning", lambda model: True)
    monkeypatch.setattr(
        models, "get_reasoning_efforts", lambda model: ["low", "medium", "high"]
    )

    reasoning, include, enabled = response_api._reasoning_config("gpt", "max")

    assert reasoning == {"effort": "medium", "summary": "auto"}
    assert include == ["reasoning.encrypted_content"]
    assert enabled is True


def test_reasoning_config_omits_unknown_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(models, "get_model_reasoning", lambda model: None)

    reasoning, include, enabled = response_api._reasoning_config("unknown", "high")

    assert reasoning is None
    assert include is None
    assert enabled is False


def test_failed_stream_surfaces_the_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = SimpleNamespace(
        type="response.failed",
        response=SimpleNamespace(
            error=SimpleNamespace(
                code="subscription_sharing_usage_limit_exceeded", message="limit"
            )
        ),
    )

    class FakeStream:
        def __iter__(self) -> Iterator[object]:
            return iter([event])

    class FakeManager:
        def __enter__(self) -> FakeStream:
            return FakeStream()

        def __exit__(self, *args: object) -> None:
            pass

    class FakeResponses:
        def stream(self, **kwargs: object) -> FakeManager:
            return FakeManager()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(
        response_api, "_reasoning_config", lambda model, effort: (None, None, False)
    )
    monkeypatch.setattr(response_api, "get_responses_client", lambda: FakeClient())

    with (
        response_api.ResponsesBackend().run_turn(request([])) as stream,
        pytest.raises(response_api.ApiError) as error,
    ):
        list(stream)

    assert "limit" in str(error.value)
    assert error.value.code == "subscription_sharing_usage_limit_exceeded"


def test_missing_completed_event_becomes_an_api_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeStream:
        def __iter__(self) -> Iterator[object]:
            return iter([])

        def get_final_response(self) -> object:
            raise RuntimeError("Didn't receive a `response.completed` event.")

    class FakeManager:
        def __enter__(self) -> FakeStream:
            return FakeStream()

        def __exit__(self, *args: object) -> None:
            pass

    class FakeResponses:
        def stream(self, **kwargs: object) -> FakeManager:
            return FakeManager()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(
        response_api, "_reasoning_config", lambda model, effort: (None, None, False)
    )
    monkeypatch.setattr(response_api, "get_responses_client", lambda: FakeClient())

    with response_api.ResponsesBackend().run_turn(request([])) as stream:
        list(stream)
        with pytest.raises(response_api.ApiError):
            stream.get_final_message()
