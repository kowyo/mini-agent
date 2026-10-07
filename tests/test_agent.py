from collections.abc import Iterator

import pytest

from mini_agent.agent import agent
from mini_agent.agent.providers.types import AssistantTurn, Message
from mini_agent.cli.token import Usage


class StatusStub:
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class ProviderStreamStub:
    def __init__(self, turn: AssistantTurn) -> None:
        self._turn = turn

    def __enter__(self) -> ProviderStreamStub:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def __iter__(self) -> Iterator[object]:
        return iter(())

    def get_final_turn(self) -> AssistantTurn:
        return self._turn


class ErrorStreamStub:
    def __enter__(self) -> ErrorStreamStub:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def __iter__(self) -> Iterator[object]:
        raise RuntimeError("The response stream failed")

    def get_final_turn(self) -> AssistantTurn:
        raise AssertionError("unreachable")


class ProviderStub:
    def __init__(self, streams: list[object]) -> None:
        self._streams = iter(streams)

    def stream(self, **kwargs: object) -> object:
        return next(self._streams)

    def list_models(self) -> list[str]:
        return []


def _usage() -> Usage:
    return Usage(
        input_tokens=1,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=1,
    )


def _install(
    monkeypatch: pytest.MonkeyPatch,
    provider: ProviderStub,
) -> None:
    monkeypatch.setattr(agent, "get_provider", lambda: provider)
    monkeypatch.setattr(agent, "get_max_output_tokens", lambda model: None)
    monkeypatch.setattr(agent.console, "status", lambda message: StatusStub())
    monkeypatch.setattr(agent, "print_tool_start", lambda name, input_data: None)
    monkeypatch.setattr(
        agent, "print_tool_result", lambda name, input_data, output: None
    )


def test_tool_error_sets_is_error_on_the_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = AssistantTurn(
        content=[{"type": "tool_use", "id": "tool-1", "name": "failing", "input": {}}],
        stop_reason="tool_use",
        usage=_usage(),
    )
    second = AssistantTurn(content=[], stop_reason="end_turn", usage=_usage())
    provider = ProviderStub([ProviderStreamStub(first), ProviderStreamStub(second)])
    _install(monkeypatch, provider)
    monkeypatch.setitem(
        agent.TOOL_HANDLERS, "failing", lambda **kw: agent.ToolError("it broke")
    )
    messages: list[Message] = [{"role": "user", "content": "Question"}]
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
    first = AssistantTurn(
        content=[{"type": "tool_use", "id": "tool-1", "name": "missing", "input": {}}],
        stop_reason="tool_use",
        usage=_usage(),
    )
    second = AssistantTurn(content=[], stop_reason="end_turn", usage=_usage())
    provider = ProviderStub([ProviderStreamStub(first), ProviderStreamStub(second)])
    _install(monkeypatch, provider)
    messages: list[Message] = [{"role": "user", "content": "Question"}]
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
    turn = AssistantTurn(
        content=[{"type": "tool_use", "id": "tool-1", "name": "unknown", "input": {}}],
        stop_reason="tool_use",
        usage=_usage(),
    )
    provider = ProviderStub([ProviderStreamStub(turn), ErrorStreamStub()])
    _install(monkeypatch, provider)
    errors: list[tuple[object, dict[str, object]]] = []
    monkeypatch.setattr(
        agent.console,
        "print",
        lambda message=None, **kwargs: errors.append((message, kwargs)),
    )
    previous_messages: list[Message] = [
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
