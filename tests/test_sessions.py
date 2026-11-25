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
