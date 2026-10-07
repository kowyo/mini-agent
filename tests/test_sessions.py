from pathlib import Path

from mini_agent.agent.providers.types import Message
from mini_agent.cli.sessions import SessionManager
from mini_agent.cli.token import Usage


def test_save_and_load_round_trip_assistant_metadata(tmp_path: Path) -> None:
    manager = SessionManager(session_dir=tmp_path)
    history: list[Message] = [
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "hi"}],
            "provider": "openai-responses",
            "model": "deepseek-v4-flash",
            "effort": "high",
        },
    ]
    usage = Usage(
        input_tokens=10,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=5,
    )

    manager.save("session-1", history, [usage], cwd=str(tmp_path))
    loaded, round_usages = manager.load("session-1")

    assert loaded == [
        {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "hi"}],
            "provider": "openai-responses",
            "model": "deepseek-v4-flash",
            "effort": "high",
        },
    ]
    assert round_usages == [usage]
