from pathlib import Path

from mini_agent.cli.sessions import SessionManager
from mini_agent.cli.token import Usage


def _text(text: str) -> list[dict[str, str]]:
    return [{"type": "text", "text": text}]


def test_compacted_history_replaces_the_original_on_load(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session_id = manager.new_id()
    history = [
        {"role": "user", "content": _text("Original question")},
        {"role": "assistant", "content": _text("Original answer")},
    ]
    manager.save(session_id, history, [Usage(10, 0, 0, 5)])

    compacted = [{"role": "user", "content": _text("This session is being continued.")}]
    manager.save(session_id, compacted, [])

    loaded, usages = manager.load(session_id)

    assert loaded == compacted
    assert usages == []


def test_compaction_keeps_the_session_title(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session_id = manager.new_id()
    manager.save(
        session_id,
        [
            {"role": "user", "content": _text("Original question")},
            {"role": "assistant", "content": _text("Original answer")},
        ],
    )
    manager.save(
        session_id,
        [{"role": "user", "content": _text("This session is being continued.")}],
    )

    sessions = manager.list_sessions()

    assert [session.title for session in sessions] == ["Original question"]


def test_messages_saved_after_compaction_are_appended(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session_id = manager.new_id()
    manager.save(
        session_id,
        [
            {"role": "user", "content": _text("Original question")},
            {"role": "assistant", "content": _text("Original answer")},
        ],
    )
    compacted = [{"role": "user", "content": _text("This session is being continued.")}]
    manager.save(session_id, compacted, [])

    continued = [
        *compacted,
        {"role": "assistant", "content": _text("Continuing")},
    ]
    manager.save(session_id, continued, [Usage(20, 0, 0, 5)])

    loaded, usages = manager.load(session_id)

    assert loaded == continued
    assert usages == [Usage(20, 0, 0, 5)]


def test_compacted_session_keeps_the_total_usage_across_resume(tmp_path: Path) -> None:
    from mini_agent.cli.token import token_tracker

    manager = SessionManager(tmp_path)
    session_id = manager.new_id()
    pre = Usage(100, 0, 0, 10)
    post = Usage(200, 0, 0, 20)
    total = Usage(500, 0, 0, 50)
    manager.save(
        session_id,
        [
            {"role": "user", "content": _text("Original question")},
            {"role": "assistant", "content": _text("Original answer")},
        ],
        [pre],
        total_usage=pre,
    )
    compacted = [{"role": "user", "content": _text("This session is being continued.")}]
    manager.save(session_id, compacted, [], total_usage=pre)
    continued = [*compacted, {"role": "assistant", "content": _text("Continuing")}]
    manager.save(session_id, continued, [post], total_usage=total)

    restored = manager.list_sessions()[0]
    previous = token_tracker.get()
    try:
        token_tracker.restore(restored.round_usages, restored.total_usage)
        assert token_tracker.get() == total
    finally:
        token_tracker.reset()
        if previous is not None:
            token_tracker.restore([previous])
