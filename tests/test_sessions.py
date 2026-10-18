import json
from pathlib import Path

from mini_agent.agent.transcript import (
    AssistantMessage,
    TextBlock,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from mini_agent.cli.sessions import SessionManager
from mini_agent.cli.token import Usage


def history() -> list:
    return [
        UserMessage(content="Question"),
        AssistantMessage(
            content=(ToolCall(id="call_1", name="bash", arguments={"command": "ls"}),),
            provider="anthropic",
            api_type="message",
            model="claude",
            usage=Usage(10, 1, 2, 3),
            stop_reason="tool_use",
            thinking_level="high",
        ),
        ToolResultMessage(
            tool_call_id="call_1",
            name="bash",
            content=(TextBlock(text="file.txt"),),
        ),
    ]


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session_id = manager.new_id()

    manager.save(session_id, history(), cwd=str(tmp_path))

    loaded, usages = manager.load(session_id)
    assert loaded == history()
    assert usages == [Usage(10, 1, 2, 3)]


def test_list_sessions_reads_v2(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session_id = manager.new_id()
    manager.save(session_id, history(), cwd=str(tmp_path))

    sessions = manager.list_sessions()

    assert len(sessions) == 1
    assert sessions[0].history == history()
    assert sessions[0].title == "Question"
    assert sessions[0].round_usages == [Usage(10, 1, 2, 3)]


def test_version_one_sessions_are_ignored(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session_id = "old-session"
    directory = manager._cwd_dir(str(tmp_path))
    directory.mkdir(parents=True)
    path = directory / f"old_{session_id}.jsonl"
    path.write_text(
        json.dumps({"type": "session", "version": 1, "id": session_id}) + "\n"
    )

    assert manager._find_file(session_id) is None
    assert manager.load(session_id) == ([], [])
    assert manager.list_sessions() == []


def test_append_only_saves_new_messages(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session_id = manager.new_id()
    initial = history()[:1]
    manager.save(session_id, initial, cwd=str(tmp_path))

    manager.save(session_id, history(), cwd=str(tmp_path))

    path = manager._find_file(session_id)
    assert path is not None
    assert len(path.read_text().splitlines()) == 4
