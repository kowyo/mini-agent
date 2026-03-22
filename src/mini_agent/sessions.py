import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from anthropic.types import MessageParam
from prompt_toolkit import PromptSession

from .config import SESSION_DIR


@dataclass
class StoredSession:
    session_id: str
    title: str
    updated_at: str
    history: list[MessageParam]


def session_path(session_id: str):
    return SESSION_DIR / f"{session_id}.jsonl"


def ensure_session_dir() -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def serialize_content(content: Any) -> Any:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        serialized_blocks: list[Any] = []
        for block in content:
            if hasattr(block, "model_dump"):
                serialized_blocks.append(block.model_dump(mode="json"))
            else:
                serialized_blocks.append(block)
        return serialized_blocks
    return content


def save_session_history(session_id: str, history: list[MessageParam]) -> None:
    ensure_session_dir()
    path = session_path(session_id)
    lines = []
    for message in history:
        lines.append(
            json.dumps(
                {
                    "role": message["role"],
                    "content": serialize_content(message["content"]),
                    "created_at": now_iso(),
                }
            )
        )
    path.write_text("\n".join(lines) + ("\n" if lines else ""))


def load_session_history(session_id: str) -> list[MessageParam]:
    path = session_path(session_id)
    history: list[MessageParam] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        history.append({"role": record["role"], "content": record["content"]})
    return history


def summarize_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                texts.append(block["text"].strip())
        return " ".join(texts).strip()
    return ""


def session_title(history: list[MessageParam]) -> str:
    for message in history:
        if message["role"] == "user":
            title = summarize_content(message["content"])
            if title:
                return title[:60]
    return "Untitled session"


def list_sessions() -> list[StoredSession]:
    ensure_session_dir()
    sessions: list[StoredSession] = []
    for path in SESSION_DIR.glob("*.jsonl"):
        try:
            history = load_session_history(path.stem)
        except OSError, json.JSONDecodeError:
            continue
        updated_at = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
        sessions.append(
            StoredSession(
                session_id=path.stem,
                title=session_title(history),
                updated_at=updated_at,
                history=history,
            )
        )
    return sorted(sessions, key=lambda item: item.updated_at, reverse=True)


def print_sessions(sessions: list[StoredSession]) -> None:
    for index, stored in enumerate(sessions, start=1):
        print(f"{index}. {stored.title} ({stored.updated_at})")


def prompt_resume(
    session: PromptSession,
    current_session_id: str,
    history: list[MessageParam],
    clear_terminal: Callable[[], None],
) -> tuple[str, list[MessageParam]]:
    sessions = list_sessions()
    if not sessions:
        print("No saved sessions found.\n")
        return current_session_id, history

    print_sessions(sessions)
    try:
        selection = session.prompt("Resume session: ").strip()
        print()
    except KeyboardInterrupt, EOFError:
        print()
        return current_session_id, history

    if not selection:
        return current_session_id, history

    chosen: StoredSession | None = None
    if selection.isdigit():
        index = int(selection) - 1
        if 0 <= index < len(sessions):
            chosen = sessions[index]
    else:
        for stored in sessions:
            if stored.session_id == selection:
                chosen = stored
                break

    if chosen is None:
        print("Invalid session selection.\n")
        return current_session_id, history

    clear_terminal()
    return chosen.session_id, chosen.history.copy()
