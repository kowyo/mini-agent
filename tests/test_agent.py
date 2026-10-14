from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from anthropic.types import MessageParam, ToolUseBlock

from mini_agent.agent import agent


class StatusStub:
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class ResponseStreamStub:
    def __init__(self, response: SimpleNamespace) -> None:
        self.response = response

    def __enter__(self) -> ResponseStreamStub:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def __iter__(self) -> Iterator[object]:
        return iter(())

    def get_final_message(self) -> SimpleNamespace:
        return self.response


class ErrorStreamStub:
    def __enter__(self) -> ErrorStreamStub:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def __iter__(self) -> Iterator[object]:
        raise RuntimeError("The response stream failed")


def test_tool_error_sets_is_error_on_the_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_use = ToolUseBlock(type="tool_use", id="tool-1", name="failing", input={})
    first = SimpleNamespace(
        content=[tool_use],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    second = SimpleNamespace(
        content=[],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    streams = iter([ResponseStreamStub(first), ResponseStreamStub(second)])

    monkeypatch.setattr(
        agent,
        "get_client",
        lambda: SimpleNamespace(
            messages=SimpleNamespace(stream=lambda **kwargs: next(streams))
        ),
    )
    monkeypatch.setattr(agent.console, "status", lambda message: StatusStub())
    monkeypatch.setattr(agent, "print_tool_start", lambda name, input_data: None)
    monkeypatch.setattr(
        agent, "print_tool_result", lambda name, input_data, output: None
    )
    monkeypatch.setitem(
        agent.TOOL_HANDLERS, "failing", lambda **kw: agent.ToolError("it broke")
    )
    messages: list[MessageParam] = [{"role": "user", "content": "Question"}]
    previous_usages = list(agent.token_tracker.round_usages)

    try:
        agent.agent_loop(messages)
        assert messages[2] == {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool-1",
                    "content": "it broke",
                    "is_error": True,
                }
            ],
        }
    finally:
        agent.token_tracker.restore(previous_usages)


def test_unknown_tool_is_reported_as_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_use = ToolUseBlock(type="tool_use", id="tool-1", name="missing", input={})
    first = SimpleNamespace(
        content=[tool_use],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    second = SimpleNamespace(
        content=[],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    streams = iter([ResponseStreamStub(first), ResponseStreamStub(second)])

    monkeypatch.setattr(
        agent,
        "get_client",
        lambda: SimpleNamespace(
            messages=SimpleNamespace(stream=lambda **kwargs: next(streams))
        ),
    )
    monkeypatch.setattr(agent.console, "status", lambda message: StatusStub())
    monkeypatch.setattr(agent, "print_tool_start", lambda name, input_data: None)
    monkeypatch.setattr(
        agent, "print_tool_result", lambda name, input_data, output: None
    )
    messages: list[MessageParam] = [{"role": "user", "content": "Question"}]
    previous_usages = list(agent.token_tracker.round_usages)

    try:
        agent.agent_loop(messages)
        assert messages[2] == {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool-1",
                    "content": "Unknown tool: missing",
                    "is_error": True,
                }
            ],
        }
    finally:
        agent.token_tracker.restore(previous_usages)


def test_stream_error_is_reported_and_discards_the_entire_incomplete_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_use = ToolUseBlock(type="tool_use", id="tool-1", name="unknown", input={})
    response = SimpleNamespace(
        content=[tool_use],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    streams = iter([ResponseStreamStub(response), ErrorStreamStub()])
    errors: list[tuple[object, dict[str, object]]] = []

    monkeypatch.setattr(
        agent,
        "get_client",
        lambda: SimpleNamespace(
            messages=SimpleNamespace(stream=lambda **kwargs: next(streams))
        ),
    )
    monkeypatch.setattr(agent.console, "status", lambda message: StatusStub())
    monkeypatch.setattr(
        agent.console,
        "print",
        lambda message=None, **kwargs: errors.append((message, kwargs)),
    )
    monkeypatch.setattr(agent, "print_tool_start", lambda name, input_data: None)
    monkeypatch.setattr(
        agent, "print_tool_result", lambda name, input_data, output: None
    )
    previous_messages: list[MessageParam] = [
        {"role": "user", "content": "Previous question"},
        {"role": "assistant", "content": "Previous answer"},
    ]
    messages = [*previous_messages, {"role": "user", "content": "New question"}]
    previous_usages = list(agent.token_tracker.round_usages)

    try:
        agent.agent_loop(messages)
        assert messages == previous_messages
        assert errors == [
            ("RuntimeError: The response stream failed", {"style": "bold red"}),
            (None, {}),
        ]
    finally:
        agent.token_tracker.restore(previous_usages)


@pytest.mark.parametrize("serialized", [False, True])
def test_codex_replay_metadata_is_not_sent_to_anthropic(serialized: bool) -> None:
    from anthropic.types import ThinkingBlock

    from mini_agent.cli.sessions import serialize_content

    thinking = ThinkingBlock(
        type="thinking",
        thinking="Summary",
        signature="codex-reasoning:encoded",
        codex_reasoning={"type": "reasoning"},
    )
    tool = ToolUseBlock(
        type="tool_use",
        id="call-1",
        name="read",
        input={"path": "README.md"},
        codex_item_id="fc-1",
    )
    history: list[MessageParam] = [
        {"role": "user", "content": "Read it"},
        {"role": "assistant", "content": [thinking, tool]},
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "contents"}
            ],
        },
    ]
    if serialized:
        history[1]["content"] = serialize_content(history[1]["content"])
    converted = agent._anthropic_history(history)
    assert converted[1]["content"] == [
        {
            "type": "tool_use",
            "id": "call-1",
            "name": "read",
            "input": {"path": "README.md"},
        }
    ]
    assert converted[2] == history[2]
    assert tool.model_extra == {"codex_item_id": "fc-1"}
    assert len(history[1]["content"]) == 2


def test_anthropic_reasoning_is_preserved() -> None:
    history: list[MessageParam] = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "thinking",
                    "thinking": "Summary",
                    "signature": "anthropic-signature",
                },
                {"type": "text", "text": "Answer"},
            ],
        }
    ]
    assert agent._anthropic_history(history) == history
