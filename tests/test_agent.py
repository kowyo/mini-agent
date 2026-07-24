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
        "client",
        SimpleNamespace(
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
