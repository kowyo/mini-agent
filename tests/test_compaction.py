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


def test_should_compact_when_the_next_request_would_not_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(compaction, "get_max_context_tokens", lambda model: 1_000_000)
    monkeypatch.setattr(
        compaction, "get_request_max_output_tokens", lambda model: 32_000
    )
    monkeypatch.setattr(compaction.config, "get_auto_compact_threshold", lambda: None)
    below = Usage(
        input_tokens=966_999,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=0,
    )
    at = Usage(
        input_tokens=967_000,
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
    reply = (
        "<analysis>Working through the request.</analysis>\n"
        "<summary>The user asked for the thing.</summary>"
    )
    stub = MessagesStub(reply)
    monkeypatch.setattr(
        compaction, "get_client", lambda: SimpleNamespace(messages=stub)
    )
    monkeypatch.setattr(compaction, "get_max_context_tokens", lambda model: 200000)
    monkeypatch.setattr(
        compaction, "get_request_max_output_tokens", lambda model: 32_000
    )
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
    assert "Summary: The user asked for the thing." in content
    assert "<analysis>" not in content
    assert "without asking the user any further questions" in content
    assert "Pick up the last task as if the break never happened." in content
    assert stub.kwargs is not None
    request_messages = stub.kwargs["messages"]
    assert isinstance(request_messages, list)
    assert request_messages[:-1] == messages
    prompt = request_messages[-1]["content"]
    assert isinstance(prompt, str)
    assert "<analysis> block followed by a <summary> block" in prompt
    assert "Only messages that actually came from the user" in prompt
    assert "Additional Instructions: the parser" in prompt


def test_compact_rejects_a_reply_without_a_summary_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = [
        {"role": "user", "content": "Do the thing"},
        {"role": "assistant", "content": "Working on it"},
    ]
    stub = MessagesStub("<analysis>No summary here.</analysis>")
    monkeypatch.setattr(
        compaction, "get_client", lambda: SimpleNamespace(messages=stub)
    )
    monkeypatch.setattr(compaction, "get_max_context_tokens", lambda model: 200000)
    monkeypatch.setattr(
        compaction, "get_request_max_output_tokens", lambda model: 32_000
    )
    monkeypatch.setattr(compaction._console, "status", lambda message: StatusStub())
    monkeypatch.setattr(
        compaction._console, "print", lambda message=None, **kwargs: None
    )

    assert compaction.compact(messages) is None


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
    monkeypatch.setattr(
        compaction, "get_request_max_output_tokens", lambda model: 32_000
    )
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
    stub = MessagesStub("<summary>Summary</summary>")
    monkeypatch.setattr(
        compaction, "get_client", lambda: SimpleNamespace(messages=stub)
    )
    monkeypatch.setattr(compaction, "get_max_context_tokens", lambda model: 1_000_000)
    monkeypatch.setattr(
        compaction, "get_request_max_output_tokens", lambda model: 32_000
    )
    monkeypatch.setattr(compaction.config, "get_auto_compact_threshold", lambda: None)
    monkeypatch.setattr(compaction._console, "status", lambda message: StatusStub())
    monkeypatch.setattr(
        compaction._console, "print", lambda message=None, **kwargs: None
    )
    previous_usages = list(token_tracker.round_usages)
    token_tracker.restore([Usage(967_000, 0, 0, 0)])

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
    monkeypatch.setattr(
        compaction, "get_request_max_output_tokens", lambda model: 32_000
    )
    monkeypatch.setattr(compaction.config, "get_auto_compact_threshold", lambda: None)
    previous_usages = list(token_tracker.round_usages)
    token_tracker.restore([Usage(967_000, 0, 0, 0)])

    try:
        assert not compaction.auto_compact(messages)
    finally:
        token_tracker.restore(previous_usages)

    assert len(messages) == 1


def test_configured_threshold_compacts_earlier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compaction, "get_max_context_tokens", lambda model: 1_000_000)
    monkeypatch.setattr(
        compaction, "get_request_max_output_tokens", lambda model: 32_000
    )
    monkeypatch.setattr(
        compaction.config, "get_auto_compact_threshold", lambda: 400_000
    )

    assert not compaction.should_compact(Usage(399_999, 0, 0, 0))
    assert compaction.should_compact(Usage(400_000, 0, 0, 0))


def test_configured_threshold_is_clamped_below_the_context_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(compaction, "get_max_context_tokens", lambda model: 1_000_000)
    monkeypatch.setattr(
        compaction, "get_request_max_output_tokens", lambda model: 32_000
    )
    monkeypatch.setattr(
        compaction.config, "get_auto_compact_threshold", lambda: 2_000_000
    )

    assert compaction.get_compact_threshold("model") == 967_000
    assert not compaction.should_compact(Usage(966_999, 0, 0, 0))
    assert compaction.should_compact(Usage(967_000, 0, 0, 0))
