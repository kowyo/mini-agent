import json
from types import SimpleNamespace
from typing import cast

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
    ResponseTextDeltaEvent,
    ResponseUsage,
)
from openai.types.responses.response_reasoning_item import Summary as ReasoningSummary
from openai.types.responses.response_reasoning_summary_part_added_event import (
    Part as ReasoningSummaryPart,
)
from openai.types.responses.response_reasoning_summary_part_done_event import (
    Part as DoneReasoningSummaryPart,
)
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
)

from mini_agent.agent.providers import openai_responses
from mini_agent.agent.providers.types import (
    BlockStart,
    BlockStop,
    Message,
    TextDelta,
    ThinkingDelta,
    ToolSpec,
)


def _output_text_part() -> ResponseOutputText:
    return ResponseOutputText(type="output_text", text="", annotations=[])


class _Stream:
    def __init__(self, response: object) -> None:
        self._response = response

    def get_final_response(self) -> object:
        return self._response


class _Manager:
    def __init__(self, stream: _Stream) -> None:
        self._stream = stream

    def __enter__(self) -> _Stream:
        return self._stream

    def __exit__(self, *args: object) -> None:
        return None


def _wrap(response: object) -> openai_responses._OpenAIStream:
    manager = cast("ResponseStreamManager[ResponseStream]", _Manager(_Stream(response)))
    return openai_responses._OpenAIStream(manager)


def test_reasoning_params_map_effort_and_request_a_detailed_summary() -> None:
    assert openai_responses._reasoning_params("disabled") == {"effort": "none"}
    assert openai_responses._reasoning_params("low") == {
        "effort": "low",
        "summary": "detailed",
    }
    assert openai_responses._reasoning_params("max") == {
        "effort": "max",
        "summary": "detailed",
    }
    assert openai_responses._reasoning_params("adaptive") == {"summary": "detailed"}


def test_tools_are_serialized_as_responses_functions() -> None:
    tools: list[ToolSpec] = [
        {
            "name": "bash",
            "description": "Run a command",
            "input_schema": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        }
    ]

    assert openai_responses._to_tools(tools) == [
        {
            "type": "function",
            "name": "bash",
            "description": "Run a command",
            "strict": False,
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        }
    ]


def test_tool_loop_history_becomes_responses_items() -> None:
    messages: list[Message] = [
        {"role": "user", "content": "prompt"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "answer"},
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "bash",
                    "input": {"command": "ls"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call_1",
                    "content": "file.txt",
                }
            ],
        },
    ]

    assert openai_responses._to_input_items(messages) == [
        {"role": "user", "content": "prompt"},
        {
            "role": "assistant",
            "content": [{"type": "input_text", "text": "answer"}],
        },
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "bash",
            "arguments": json.dumps({"command": "ls"}),
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "file.txt",
        },
    ]


def test_trailing_text_message_collapses_to_a_string() -> None:
    messages: list[Message] = [
        {"role": "assistant", "content": [{"type": "text", "text": "done"}]}
    ]

    assert openai_responses._to_input_items(messages) == [
        {"role": "assistant", "content": "done"}
    ]


def test_user_image_is_sent_as_a_data_url() -> None:
    messages: list[Message] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "AAAA",
                    },
                }
            ],
        }
    ]

    assert openai_responses._to_input_items(messages) == [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_image",
                    "image_url": "data:image/png;base64,AAAA",
                    "detail": "auto",
                }
            ],
        }
    ]


def test_output_items_become_neutral_blocks() -> None:
    output = [
        ResponseReasoningItem(
            id="r1",
            type="reasoning",
            summary=[ReasoningSummary(type="summary_text", text="thinking")],
        ),
        ResponseOutputMessage(
            id="m1",
            type="message",
            role="assistant",
            status="completed",
            content=[
                ResponseOutputText(type="output_text", text="hello", annotations=[])
            ],
        ),
        ResponseFunctionToolCall(
            type="function_call",
            call_id="call_1",
            name="bash",
            arguments=json.dumps({"command": "ls"}),
        ),
    ]

    assert openai_responses._blocks_from_output(output) == [
        {"type": "thinking", "thinking": "thinking"},
        {"type": "text", "text": "hello"},
        {
            "type": "tool_use",
            "id": "call_1",
            "name": "bash",
            "input": {"command": "ls"},
        },
    ]


def test_usage_subtracts_cached_tokens_from_input() -> None:
    usage = ResponseUsage(
        input_tokens=100,
        input_tokens_details=InputTokensDetails(cache_write_tokens=0, cached_tokens=40),
        output_tokens=10,
        output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        total_tokens=110,
    )

    assert openai_responses._usage_from_response(usage) == openai_responses.Usage(
        input_tokens=60,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=40,
        output_tokens=10,
    )


def test_response_stream_events_are_mapped_to_neutral_events() -> None:
    events: list[object] = [
        ResponseContentPartAddedEvent(
            type="response.content_part.added",
            item_id="i1",
            output_index=0,
            content_index=0,
            sequence_number=1,
            part=_output_text_part(),
        ),
        ResponseTextDeltaEvent(
            type="response.output_text.delta",
            item_id="i1",
            output_index=0,
            content_index=0,
            sequence_number=2,
            delta="hello",
            logprobs=[],
        ),
        ResponseContentPartDoneEvent(
            type="response.content_part.done",
            item_id="i1",
            output_index=0,
            content_index=0,
            sequence_number=3,
            part=_output_text_part(),
        ),
        ResponseReasoningSummaryPartAddedEvent(
            type="response.reasoning_summary_part.added",
            item_id="r1",
            output_index=0,
            summary_index=0,
            sequence_number=4,
            part=ReasoningSummaryPart(type="summary_text", text=""),
        ),
        ResponseReasoningSummaryTextDeltaEvent(
            type="response.reasoning_summary_text.delta",
            item_id="r1",
            output_index=0,
            summary_index=0,
            sequence_number=5,
            delta="hmm",
        ),
        ResponseReasoningSummaryPartDoneEvent(
            type="response.reasoning_summary_part.done",
            item_id="r1",
            output_index=0,
            summary_index=0,
            sequence_number=6,
            part=DoneReasoningSummaryPart(type="summary_text", text=""),
        ),
    ]

    assert list(openai_responses._events_from_response_stream(iter(events))) == [
        BlockStart(kind="text"),
        TextDelta(text="hello"),
        BlockStop(),
        BlockStart(kind="thinking"),
        ThinkingDelta(text="hmm"),
        BlockStop(),
    ]


def test_final_turn_reports_tool_use_and_usage() -> None:
    response = SimpleNamespace(
        output=[
            ResponseOutputMessage(
                id="m1",
                type="message",
                role="assistant",
                status="completed",
                content=[
                    ResponseOutputText(type="output_text", text="hello", annotations=[])
                ],
            ),
            ResponseFunctionToolCall(
                type="function_call",
                call_id="call_1",
                name="bash",
                arguments=json.dumps({"command": "ls"}),
            ),
        ],
        usage=ResponseUsage(
            input_tokens=10,
            input_tokens_details=InputTokensDetails(
                cache_write_tokens=0, cached_tokens=0
            ),
            output_tokens=2,
            output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
            total_tokens=12,
        ),
    )

    with _wrap(response) as stream:
        turn = stream.get_final_turn()

    assert turn.content == [
        {"type": "text", "text": "hello"},
        {
            "type": "tool_use",
            "id": "call_1",
            "name": "bash",
            "input": {"command": "ls"},
        },
    ]
    assert turn.stop_reason == "tool_use"
    assert turn.usage.input_tokens == 10
    assert turn.usage.output_tokens == 2
