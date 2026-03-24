import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from anthropic.types import MessageParam
from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from pydantic import BaseModel

from ..config import SESSION_DIR
from .display import (
    clear_terminal,
    print_session_history,
    print_welcome_banner,
)


@dataclass
class StoredSession:
    session_id: str
    title: str
    updated_at: str
    history: list[MessageParam]


def session_path(session_id: str) -> Path:
    return SESSION_DIR / f"{session_id}.jsonl"


def ensure_session_dir() -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)


def serialize_content(content: str | Iterable[object]) -> str | list[object]:
    if isinstance(content, str):
        return content
    serialized_blocks: list[object] = []
    for block in content:
        if isinstance(block, BaseModel):
            serialized_blocks.append(block.model_dump(mode="json"))
        else:
            serialized_blocks.append(block)
    return serialized_blocks


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


def summarize_content(content: str | Iterable[object]) -> str:
    if isinstance(content, str):
        return content.strip()
    texts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = cast(dict[str, object], block).get("text")
        if isinstance(text, str):
            texts.append(text.strip())
    return " ".join(texts).strip()


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
        except OSError:
            continue
        except json.JSONDecodeError:
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


def format_relative_time(timestamp: str) -> str:
    updated_at = datetime.fromisoformat(timestamp)
    now = datetime.now(UTC)
    delta = now - updated_at.astimezone(UTC)
    seconds = max(int(delta.total_seconds()), 0)

    if seconds < 60:
        return "just now"
    if seconds < 3600:
        minutes = seconds // 60
        unit = "minute" if minutes == 1 else "minutes"
        return f"{minutes} {unit} ago"
    if seconds < 86400:
        hours = seconds // 3600
        unit = "hour" if hours == 1 else "hours"
        return f"{hours} {unit} ago"

    days = seconds // 86400
    unit = "day" if days == 1 else "days"
    return f"{days} {unit} ago"


def format_session_choice(stored: StoredSession) -> str:
    return f"{stored.title} ({format_relative_time(stored.updated_at)})"


def select_session(sessions: list[StoredSession]) -> str | None:
    selected_index = 0

    def render() -> FormattedText:
        fragments: list[tuple[str, str]] = [
            ("", "Resume a previous session\n\n"),
        ]
        for index, stored in enumerate(sessions):
            prefix = "> " if index == selected_index else "  "
            fragments.append(("", f"{prefix}{format_session_choice(stored)}\n"))
        return FormattedText(fragments)

    bindings = KeyBindings()

    @bindings.add("up")
    def move_up(event: KeyPressEvent) -> None:
        nonlocal selected_index
        selected_index = (selected_index - 1) % len(sessions)
        event.app.invalidate()

    @bindings.add("down")
    def move_down(event: KeyPressEvent) -> None:
        nonlocal selected_index
        selected_index = (selected_index + 1) % len(sessions)
        event.app.invalidate()

    @bindings.add("enter")
    def accept(event: KeyPressEvent) -> None:
        event.app.exit(result=sessions[selected_index].session_id)

    @bindings.add("escape")
    @bindings.add("c-c")
    def cancel(event: KeyPressEvent) -> None:
        event.app.exit(result=None)

    application = Application(
        layout=Layout(Window(FormattedTextControl(render), always_hide_cursor=True)),
        key_bindings=bindings,
        full_screen=False,
        mouse_support=False,
        style=None,
    )
    return application.run()


def prompt_resume(
    current_session_id: str,
    history: list[MessageParam],
) -> tuple[str, list[MessageParam]]:
    clear_terminal()
    sessions = list_sessions()
    if not sessions:
        print("No saved sessions found.\n")
        return current_session_id, history

    result = select_session(sessions)
    print()

    if result is None:
        clear_terminal()
        print_welcome_banner()
        print_session_history(history)
        return current_session_id, history

    chosen = next(stored for stored in sessions if stored.session_id == result)

    clear_terminal()
    print_welcome_banner()
    print_session_history(chosen.history)
    return chosen.session_id, chosen.history.copy()
