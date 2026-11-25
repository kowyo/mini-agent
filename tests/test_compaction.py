from types import SimpleNamespace

import pytest
from anthropic.types import TextBlock

from mini_agent.agent import compaction
from mini_agent.cli.token import Usage, token_tracker


class StatusStub:
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class MessagesStub:
    def __init__(self, text: str) -> None:
        self.text = text
        self.kwargs: dict[str, object] | None = None

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.kwargs = kwargs
        return SimpleNamespace(content=[TextBlock(type="text", text=self.text)])


def test_should_compact_only_when_output_headroom_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(compaction, "get_max_context_tokens", lambda model: 1_000_000)
    monkeypatch.setattr(compaction, "get_max_output_tokens", lambda model: 20_000)
    below = Usage(
        input_tokens=979_999,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=0,
    )
    at = Usage(
        input_tokens=980_000,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=0,
    )

    assert not compaction.should_compact(None)
    assert not compaction.should_compact(below)
    assert compaction.should_compact(at)


def test_compact_replaces_the_history_with_a_continuation_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = [
        {"role": "user", "content": "Do the thing"},
        {"role": "assistant", "content": "Working on it"},
    ]
    stub = MessagesStub("The user asked for the thing.")
    monkeypatch.setattr(
        compaction, "get_client", lambda: SimpleNamespace(messages=stub)
    )
    monkeypatch.setattr(compaction, "get_max_context_tokens", lambda model: 200000)
    monkeypatch.setattr(compaction._console, "status", lambda message: StatusStub())
    previous_usages = list(token_tracker.round_usages)

    try:
        result = compaction.compact(messages, focus="the parser")
    finally:
        token_tracker.restore(previous_usages)

    assert result is not None
    assert len(result) == 1
    content = result[0]["content"]
    assert isinstance(content, str)
    assert content.startswith("This session is being continued")
    assert "<summary>\nThe user asked for the thing.\n</summary>" in content
    assert stub.kwargs is not None
    request_messages = stub.kwargs["messages"]
    assert isinstance(request_messages, list)
    assert request_messages[:-1] == messages
    assert "Focus especially on: the parser" in request_messages[-1]["content"]


def test_compact_keeps_the_history_when_summarization_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = [
        {"role": "user", "content": "Do the thing"},
        {"role": "assistant", "content": "Working on it"},
    ]

    class FailingMessages:
        def create(self, **kwargs: object) -> SimpleNamespace:
            raise RuntimeError("boom")

    monkeypatch.setattr(
        compaction, "get_client", lambda: SimpleNamespace(messages=FailingMessages())
    )
    monkeypatch.setattr(compaction, "get_max_context_tokens", lambda model: 200000)
    monkeypatch.setattr(compaction._console, "status", lambda message: StatusStub())
    monkeypatch.setattr(
        compaction._console, "print", lambda message=None, **kwargs: None
    )

    assert compaction.compact(messages) is None
    assert len(messages) == 2


def test_auto_compact_rewrites_the_history_when_context_is_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = [
        {"role": "user", "content": "Do the thing"},
        {"role": "assistant", "content": "Working on it"},
    ]
    stub = MessagesStub("Summary")
    monkeypatch.setattr(
        compaction, "get_client", lambda: SimpleNamespace(messages=stub)
    )
    monkeypatch.setattr(compaction, "get_max_context_tokens", lambda model: 1_000_000)
    monkeypatch.setattr(compaction, "get_max_output_tokens", lambda model: 20_000)
    monkeypatch.setattr(compaction._console, "status", lambda message: StatusStub())
    monkeypatch.setattr(
        compaction._console, "print", lambda message=None, **kwargs: None
    )
    previous_usages = list(token_tracker.round_usages)
    token_tracker.restore([Usage(980_000, 0, 0, 0)])

    try:
        assert compaction.auto_compact(messages)
    finally:
        token_tracker.restore(previous_usages)

    assert len(messages) == 1
    assert str(messages[0]["content"]).startswith("This session is being continued")


def test_auto_compact_leaves_a_compacted_history_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = [{"role": "user", "content": "This session is being continued"}]
    monkeypatch.setattr(compaction, "get_max_context_tokens", lambda model: 1_000_000)
    monkeypatch.setattr(compaction, "get_max_output_tokens", lambda model: 20_000)
    previous_usages = list(token_tracker.round_usages)
    token_tracker.restore([Usage(980_000, 0, 0, 0)])

    try:
        assert not compaction.auto_compact(messages)
    finally:
        token_tracker.restore(previous_usages)

    assert len(messages) == 1
