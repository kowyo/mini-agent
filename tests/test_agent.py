from collections.abc import Iterator

import pytest

from mini_agent.agent import agent
from mini_agent.agent.api.base import TurnRequest, TurnStream
from mini_agent.agent.transcript import (
    AssistantMessage,
    Message,
    TextBlock,
    ToolCall,
    ToolResultMessage,
    Transcript,
    UserMessage,
)
from mini_agent.cli.token import Usage
from mini_agent.config import Provider


class StatusStub:
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class ConfigStub:
    def get_provider(self) -> Provider:
        return Provider(
            id="test",
            name="Test",
            base_url="https://example.com",
            api_type="message",
        )

    def get_model(self) -> str:
        return "test-model"

    def get_reasoning_effort(self) -> str:
        return "disabled"


class TurnStreamStub:
    def __init__(self, message: AssistantMessage | None = None) -> None:
        self.message = message

    def __enter__(self) -> TurnStreamStub:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def __iter__(self) -> Iterator[object]:
        return iter(())

    def get_final_message(self) -> AssistantMessage:
        if self.message is None:
            raise RuntimeError("The response stream failed")
        return self.message


class ErrorTurnStream(TurnStreamStub):
    def __iter__(self) -> Iterator[object]:
        raise RuntimeError("The response stream failed")


class BackendStub:
    def __init__(self, streams: list[TurnStreamStub]) -> None:
        self.streams = iter(streams)

    def run_turn(self, request: TurnRequest) -> TurnStream:
        return next(self.streams)


def assistant(
    content: tuple[TextBlock | ToolCall, ...], stop_reason: str
) -> AssistantMessage:
    return AssistantMessage(
        content=content,
        provider="test",
        api_type="message",
        model="test-model",
        usage=Usage(1, 0, 0, 1),
        stop_reason=stop_reason,
    )


def transcript() -> Transcript:
    return Transcript(
        system="system",
        tools=[],
        messages=[UserMessage(content="Question")],
    )


def setup_agent(
    monkeypatch: pytest.MonkeyPatch,
    streams: list[TurnStreamStub],
) -> None:
    backend = BackendStub(streams)
    monkeypatch.setattr(agent, "get_backend", lambda provider: backend)
    monkeypatch.setattr(agent, "config", ConfigStub())
    monkeypatch.setattr(agent._console, "status", lambda message: StatusStub())
    monkeypatch.setattr(agent, "print_tool_start", lambda name, input_data: None)
    monkeypatch.setattr(
        agent, "print_tool_result", lambda name, input_data, output: None
    )


def test_tool_error_sets_is_error_on_the_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = assistant(
        (ToolCall(id="tool-1", name="failing", arguments={}),),
        "tool_use",
    )
    second = assistant((), "end_turn")
    setup_agent(
        monkeypatch,
        [TurnStreamStub(first), TurnStreamStub(second)],
    )
    monkeypatch.setitem(
        agent.TOOL_HANDLERS, "failing", lambda **kw: agent.ToolError("it broke")
    )
    history = transcript()
    previous_usages = list(agent.token_tracker.round_usages)

    try:
        agent.agent_loop(history)
        result = history.messages[2]
        assert isinstance(result, ToolResultMessage)
        assert result == ToolResultMessage(
            tool_call_id="tool-1",
            name="failing",
            content=(TextBlock(text="it broke"),),
            is_error=True,
        )
    finally:
        agent.token_tracker.restore(previous_usages)


def test_unknown_tool_is_reported_as_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = assistant(
        (ToolCall(id="tool-1", name="missing", arguments={}),),
        "tool_use",
    )
    second = assistant((), "end_turn")
    setup_agent(
        monkeypatch,
        [TurnStreamStub(first), TurnStreamStub(second)],
    )
    history = transcript()
    previous_usages = list(agent.token_tracker.round_usages)

    try:
        agent.agent_loop(history)
        result = history.messages[2]
        assert isinstance(result, ToolResultMessage)
        assert result.is_error is True
        assert result.content == (TextBlock(text="Unknown tool: missing"),)
    finally:
        agent.token_tracker.restore(previous_usages)


def test_stream_error_is_reported_and_discards_the_entire_incomplete_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = assistant(
        (ToolCall(id="tool-1", name="unknown", arguments={}),),
        "tool_use",
    )
    setup_agent(
        monkeypatch,
        [TurnStreamStub(first), ErrorTurnStream()],
    )
    errors: list[tuple[object, dict[str, object]]] = []
    monkeypatch.setattr(
        agent._console,
        "print",
        lambda message=None, **kwargs: errors.append((message, kwargs)),
    )
    previous: list[Message] = [
        UserMessage(content="Previous question"),
        assistant((TextBlock(text="Previous answer"),), "end_turn"),
    ]
    history = Transcript(
        system="system",
        tools=[],
        messages=[*previous, UserMessage(content="New question")],
    )
    previous_usages = list(agent.token_tracker.round_usages)

    try:
        agent.agent_loop(history)
        assert history.messages == previous
        assert errors == [
            ("RuntimeError: The response stream failed", {"style": "bold red"}),
            (None, {}),
        ]
    finally:
        agent.token_tracker.restore(previous_usages)
