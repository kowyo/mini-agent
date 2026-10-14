import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from anthropic.types import Message, TextDelta, ThinkingBlock, ToolUseBlock

from mini_agent.chatgpt import CODEX_URL, ChatGPTClient, ChatGPTError
from mini_agent.cli.sessions import serialize_content
from mini_agent.oauth import Credentials

CREDENTIALS = Credentials("secret", "refresh", "account", 9999999999)
KWARGS = {
    "model": "gpt-5.4",
    "messages": [{"role": "user", "content": "Hello"}],
    "system": "Be helpful",
    "max_tokens": 100,
}
TEXT = {
    "type": "message",
    "id": "msg_1",
    "role": "assistant",
    "content": [{"type": "output_text", "text": "Hello!"}],
}
TOOL = {
    "type": "function_call",
    "id": "fc_1",
    "call_id": "call_1",
    "name": "bash",
    "arguments": '{"command":"pwd"}',
}
REASONING = {
    "type": "reasoning",
    "id": "rs_1",
    "summary": [{"type": "summary_text", "text": "Think"}],
    "encrypted_content": "opaque",
}


def completed(output: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "response.completed",
        "response": {
            "id": "resp_1",
            "status": "completed",
            "output": output,
            "usage": {
                "input_tokens": 100,
                "input_tokens_details": {"cached_tokens": 30},
                "output_tokens": 10,
            },
        },
    }


def sse(*events: dict[str, Any]) -> bytes:
    return (
        ": heartbeat\n\n"
        + "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
    ).encode()


@pytest.mark.parametrize("terminal_output", [None, [], [TEXT], "omitted"])
def test_done_items_survive_terminal_output(terminal_output: object) -> None:
    terminal = completed([])
    if terminal_output == "omitted":
        terminal["response"].pop("output")
    else:
        terminal["response"]["output"] = terminal_output
    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=sse(
            {"type": "response.output_item.done", "output_index": 0, "item": REASONING},
            {"type": "response.output_item.done", "output_index": 2, "item": TEXT},
            {"type": "response.output_item.done", "output_index": 4, "item": TOOL},
            terminal,
        ),
    )
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: response)) as http,
        ChatGPTClient(
            http_client=http, credentials=lambda: CREDENTIALS
        ).messages.stream(**KWARGS) as stream,
    ):
        events = list(stream)
        final = stream.get_final_message()
    assert final.stop_reason == "tool_use"
    assert [block.type for block in final.content] == ["thinking", "text", "tool_use"]
    assert final.content[0].thinking == "Think"
    assert final.content[1].text == "Hello!"
    assert final.content[2].id == "call_1"
    assert final.content[2].input == {"command": "pwd"}
    # Sparse output indices must not produce duplicate content blocks at completion.
    assert len([e for e in events if e.type == "content_block_start"]) == 3
    assert len([e for e in events if e.type == "content_block_stop"]) == 3
    assert response.is_closed


@pytest.mark.parametrize("terminal_output", [None, {}, [None]])
def test_invalid_terminal_output_without_done_items(terminal_output: object) -> None:
    terminal = completed([])
    terminal["response"]["output"] = terminal_output
    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=sse(terminal),
    )
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: response)) as http,
        ChatGPTClient(
            http_client=http, credentials=lambda: CREDENTIALS
        ).messages.stream(**KWARGS) as stream,
        pytest.raises(ChatGPTError, match="invalid terminal output"),
    ):
        stream.get_final_message()
    assert response.is_closed


def test_text_request_stream_and_usage() -> None:
    requests = []
    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=sse(
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {**TEXT, "content": []},
            },
            {
                "type": "response.output_text.delta",
                "output_index": 0,
                "content_index": 0,
                "delta": "Hello!",
            },
            {"type": "response.output_item.done", "output_index": 0, "item": TEXT},
            completed([TEXT]),
        ),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return response

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = ChatGPTClient(http_client=http, credentials=lambda: CREDENTIALS)
        with client.messages.stream(**KWARGS) as stream:
            events = list(stream)
            final = stream.get_final_message()
        assert not http.is_closed
    assert response.is_closed
    assert isinstance(final, Message)
    assert final.content[0].text == "Hello!"
    assert final.stop_reason == "end_turn"
    assert final.usage.input_tokens == 70
    assert final.usage.cache_read_input_tokens == 30
    assert final.usage.output_tokens == 10
    assert [e.type for e in events] == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    assert isinstance(events[2].delta, TextDelta)
    request = requests[0]
    assert str(request.url) == CODEX_URL
    assert request.headers["authorization"] == "Bearer secret"
    assert request.headers["chatgpt-account-id"] == "account"
    body = json.loads(request.content)
    assert body["stream"] is True
    assert body["store"] is False
    assert body["instructions"] == "Be helpful"
    assert "max_tokens" not in body
    assert "max_output_tokens" not in body


def test_tools_reasoning_and_serialized_continuation() -> None:
    requests = []
    credentials_calls = []

    def credentials() -> Credentials:
        credentials_calls.append(True)
        return CREDENTIALS

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {**REASONING, "summary": []},
                },
                {
                    "type": "response.reasoning_summary_text.delta",
                    "output_index": 0,
                    "summary_index": 0,
                    "delta": "Think",
                },
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": REASONING,
                },
                {
                    "type": "response.output_item.added",
                    "output_index": 1,
                    "item": {**TOOL, "arguments": ""},
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "output_index": 1,
                    "delta": TOOL["arguments"],
                },
                {"type": "response.output_item.done", "output_index": 1, "item": TOOL},
                completed([REASONING, TOOL]),
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = ChatGPTClient(http_client=http, credentials=credentials)
        kwargs = {
            **KWARGS,
            "tools": [
                {
                    "name": "bash",
                    "description": "Run",
                    "input_schema": {"type": "object"},
                }
            ],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": "max"},
        }
        with client.messages.stream(**kwargs) as stream:
            events = list(stream)
            final = stream.get_final_message()
        assert isinstance(final.content[0], ThinkingBlock)
        assert isinstance(final.content[1], ToolUseBlock)
        assert final.content[1].id == "call_1"
        assert final.content[1].input == {"command": "pwd"}
        assert final.stop_reason == "tool_use"
        # Real session serializer retains the opaque reasoning and distinct item ID.
        history = [
            *KWARGS["messages"],
            {
                "role": "assistant",
                "content": json.loads(json.dumps(serialize_content(final.content))),
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "call_1", "content": "/tmp"}
                ],
            },
        ]
        with client.messages.stream(**{**kwargs, "messages": history}) as stream:
            stream.get_final_message()
    assert len(credentials_calls) == 2
    assert requests[0]["reasoning"] == {"effort": "xhigh", "summary": "auto"}
    assert requests[0]["tools"][0]["parameters"] == {"type": "object"}
    assert requests[1]["input"][1] == REASONING
    assert requests[1]["input"][2]["id"] == "fc_1"
    assert requests[1]["input"][2]["call_id"] == "call_1"
    assert requests[1]["input"][3] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "/tmp",
    }
    assert any(
        e.type == "content_block_delta" and e.delta.type == "signature_delta"
        for e in events
    )


def test_image_and_foreign_reasoning_history() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(completed([TEXT])),
        )

    image = {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "YWJj"},
    }
    messages = [
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "foreign", "signature": "anthropic"},
                {"type": "text", "text": "Describe it"},
            ],
        },
        {
            "role": "user",
            "content": [
                image,
                {
                    "type": "image",
                    "source": {"type": "url", "url": "https://example.com/image.png"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call", "content": [image]}
            ],
        },
    ]
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as http,
        ChatGPTClient(
            http_client=http, credentials=lambda: CREDENTIALS
        ).messages.stream(**{**KWARGS, "messages": messages}) as stream,
    ):
        stream.get_final_message()
    inputs = requests[0]["input"]
    assert inputs[0]["content"] == [{"type": "output_text", "text": "Describe it"}]
    assert inputs[1]["content"][0]["image_url"] == "data:image/png;base64,YWJj"
    assert inputs[1]["content"][1]["image_url"] == "https://example.com/image.png"
    assert inputs[2]["output"][0]["type"] == "input_image"


@pytest.mark.parametrize("kind", ["response.failed", "response.incomplete", "error"])
def test_terminal_errors_are_safe(kind: str) -> None:
    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=sse({"type": kind, "error": {"message": "secret"}}),
    )
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: response)) as http,
        ChatGPTClient(
            http_client=http, credentials=lambda: CREDENTIALS
        ).messages.stream(**KWARGS) as stream,
        pytest.raises(ChatGPTError, match=kind) as exc,
    ):
        stream.get_final_message()
    assert "secret" not in str(exc.value)
    assert response.is_closed


@pytest.mark.parametrize(
    "payload", [b"data: invalid\n\n", b"data: {}\n", b"data: [DONE]\n\n", b""]
)
def test_malformed_or_truncated_stream(payload: bytes) -> None:
    response = httpx.Response(
        200, headers={"content-type": "text/event-stream"}, content=payload
    )
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: response)) as http,
        ChatGPTClient(
            http_client=http, credentials=lambda: CREDENTIALS
        ).messages.stream(**KWARGS) as stream,
        pytest.raises(ChatGPTError),
    ):
        stream.get_final_message()
    assert response.is_closed


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_http_errors_do_not_expose_body(status: int) -> None:
    response = httpx.Response(status, text="secret credentials")
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: response)) as http,
        pytest.raises(ChatGPTError, match=str(status)) as exc,
        ChatGPTClient(
            http_client=http, credentials=lambda: CREDENTIALS
        ).messages.stream(**KWARGS),
    ):
        pass
    assert "secret" not in str(exc.value)
    assert response.is_closed


class InterruptedStream(httpx.SyncByteStream):
    def __init__(self) -> None:
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        yield b": heartbeat\n\n"
        raise KeyboardInterrupt

    def close(self) -> None:
        self.closed = True


def test_interrupt_closes_connection() -> None:
    body = InterruptedStream()
    response = httpx.Response(
        200, headers={"content-type": "text/event-stream"}, stream=body
    )
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: response)) as http,
        pytest.raises(KeyboardInterrupt),
        ChatGPTClient(
            http_client=http, credentials=lambda: CREDENTIALS
        ).messages.stream(**KWARGS) as stream,
    ):
        stream.get_final_message()
    assert body.closed
    assert response.is_closed


def test_multiple_final_only_blocks() -> None:
    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=sse(
            completed(
                [
                    TEXT,
                    {**TEXT, "id": "msg_2"},
                    TOOL,
                    {**TOOL, "id": "fc_2", "call_id": "call_2"},
                ]
            )
        ),
    )
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: response)) as http,
        ChatGPTClient(
            http_client=http, credentials=lambda: CREDENTIALS
        ).messages.stream(**KWARGS) as stream,
    ):
        events = list(stream)
        final = stream.get_final_message()
    assert len(final.content) == 4
    assert len([e for e in events if e.type == "content_block_start"]) == 4
    assert len([e for e in events if e.type == "content_block_stop"]) == 4


def test_connection_error_is_safe() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret", request=request)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as http,
        pytest.raises(ChatGPTError, match="connection failed") as exc,
        ChatGPTClient(
            http_client=http, credentials=lambda: CREDENTIALS
        ).messages.stream(**KWARGS),
    ):
        pass
    assert "secret" not in str(exc.value)


def test_invalid_function_arguments_never_execute() -> None:
    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=sse(completed([{**TOOL, "arguments": "[]"}])),
    )
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: response)) as http,
        ChatGPTClient(
            http_client=http, credentials=lambda: CREDENTIALS
        ).messages.stream(**KWARGS) as stream,
        pytest.raises(ChatGPTError, match="invalid function arguments"),
    ):
        stream.get_final_message()
    assert response.is_closed


def test_multiple_reasoning_summaries_form_one_thinking_block() -> None:
    reasoning = {
        **REASONING,
        "summary": [
            {"type": "summary_text", "text": "One"},
            {"type": "summary_text", "text": "Two"},
        ],
    }
    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=sse(
            {
                "type": "response.reasoning_summary_text.delta",
                "output_index": 0,
                "summary_index": 0,
                "delta": "One",
            },
            {
                "type": "response.reasoning_summary_text.delta",
                "output_index": 0,
                "summary_index": 1,
                "delta": "Two",
            },
            {"type": "response.output_item.done", "output_index": 0, "item": reasoning},
            completed([reasoning]),
        ),
    )
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: response)) as http,
        ChatGPTClient(
            http_client=http, credentials=lambda: CREDENTIALS
        ).messages.stream(**KWARGS) as stream,
    ):
        events = list(stream)
        final = stream.get_final_message()
    assert final.content[0].thinking == "One\nTwo"
    assert len([e for e in events if e.type == "content_block_start"]) == 1
    assert len([e for e in events if e.type == "content_block_stop"]) == 1
    assert (
        "".join(
            e.delta.thinking
            for e in events
            if e.type == "content_block_delta" and e.delta.type == "thinking_delta"
        )
        == "One\nTwo"
    )
