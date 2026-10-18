import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..agent.transcript import (
    AssistantMessage,
    Message,
    UserMessage,
    message_from_dict,
    message_to_dict,
    text_content,
)
from ..config import SESSION_DIR
from .display import clear_terminal, print_session_history
from .display.picker import select_from_list
from .token import Usage, token_tracker


@dataclass
class _StoredSession:
    session_id: str
    title: str
    _updated_at: str
    history: list[Message]
    round_usages: list[Usage]


def _message_usage(message: Message) -> Usage | None:
    if isinstance(message, AssistantMessage):
        return message.usage
    return None


def _session_title(history: list[Message]) -> str:
    for message in history:
        if isinstance(message, UserMessage):
            title = " ".join(text_content(message.content).splitlines()).strip()
            if title:
                return title[:60]
    return "Untitled session"


class SessionManager:
    _VERSION = 2

    def __init__(self, session_dir: Path | None = None) -> None:
        self._base_dir = session_dir or SESSION_DIR

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid7())

    @staticmethod
    def _entry_id() -> str:
        return uuid.uuid4().hex[:8]

    def _cwd_dir(self, cwd: str | None = None) -> Path:
        cwd = cwd or str(Path.cwd())
        resolved = str(Path(cwd).resolve())
        safe = resolved.lstrip("/").replace("/", "-").replace(":", "-")
        return self._base_dir / (safe or "__root__")

    def _is_current(self, path: Path) -> bool:
        try:
            with path.open() as file:
                header = json.loads(file.readline())
        except OSError, json.JSONDecodeError:
            return False
        return header.get("version") == self._VERSION

    def _find_file(self, session_id: str) -> Path | None:
        if not self._base_dir.exists():
            return None
        for _cwd_dir in self._base_dir.iterdir():
            if not _cwd_dir.is_dir():
                continue
            for path in _cwd_dir.glob(f"*_{session_id}.jsonl"):
                if self._is_current(path):
                    return path
        return None

    def exists(self, session_id: str) -> bool:
        return self._find_file(session_id) is not None

    def save(
        self,
        session_id: str,
        history: list[Message],
        cwd: str | None = None,
    ) -> None:
        cwd = cwd or str(Path.cwd())
        session_dir = self._cwd_dir(cwd)
        session_dir.mkdir(parents=True, exist_ok=True)

        existing = self._find_file(session_id)
        entries: list[dict[str, Any]]
        if existing:
            lines = [line for line in existing.read_text().splitlines() if line.strip()]
            try:
                entries = [json.loads(line) for line in lines]
            except json.JSONDecodeError as err:
                raise ValueError(f"Invalid JSON in session file: {existing}") from err
        else:
            entries = []

        existing_entry_count = max(len(entries) - 1, 0) if entries else 0

        for message in history[existing_entry_count:]:
            now = datetime.now(UTC)
            entries.append(
                {
                    "type": "message",
                    "id": self._entry_id(),
                    "timestamp": int(now.timestamp() * 1000),
                    "message": message_to_dict(message),
                }
            )

        if existing:
            path = existing
        else:
            now = datetime.now(UTC)
            ts = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            header = {
                "type": "session",
                "version": self._VERSION,
                "id": session_id,
                "timestamp": ts,
                "cwd": cwd,
            }
            file_timestamp = ts.replace(":", "-").replace(".", "-")
            path = session_dir / f"{file_timestamp}_{session_id}.jsonl"
            entries.insert(0, header)

        path.write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n"
        )

    def load(self, session_id: str) -> tuple[list[Message], list[Usage]]:
        path = self._find_file(session_id)
        if path is None:
            return [], []

        lines = [line for line in path.read_text().splitlines() if line.strip()]
        if not lines:
            return [], []
        try:
            header = json.loads(lines[0])
        except json.JSONDecodeError:
            return [], []
        if header.get("version") != self._VERSION:
            return [], []

        history: list[Message] = []
        round_usages: list[Usage] = []
        for line in lines[1:]:
            try:
                entry = json.loads(line)
                message = message_from_dict(entry["message"])
            except json.JSONDecodeError, KeyError, ValueError, TypeError:
                continue
            history.append(message)
            usage = _message_usage(message)
            if usage is not None:
                round_usages.append(usage)
        return history, round_usages

    def list_sessions(self) -> list[_StoredSession]:
        if not self._base_dir.exists():
            return []
        sessions: list[_StoredSession] = []
        for _cwd_dir in self._base_dir.iterdir():
            if not _cwd_dir.is_dir():
                continue
            for path in _cwd_dir.glob("*.jsonl"):
                try:
                    content = path.read_text()
                    lines = [line for line in content.splitlines() if line.strip()]
                    if not lines:
                        continue
                    header = json.loads(lines[0])
                    if header.get("type") != "session":
                        continue
                    if header.get("version") != self._VERSION:
                        continue
                    sid = header.get("id", "")
                    if not sid:
                        continue
                    max_ts = 0
                    history: list[Message] = []
                    round_usages: list[Usage] = []
                    for line in lines[1:]:
                        entry = json.loads(line)
                        message = message_from_dict(entry["message"])
                        history.append(message)
                        ts = entry.get("timestamp", 0)
                        if ts > max_ts:
                            max_ts = ts
                        usage = _message_usage(message)
                        if usage is not None:
                            round_usages.append(usage)
                    _updated_at = (
                        datetime.fromtimestamp(max_ts / 1000, UTC).isoformat()
                        if max_ts
                        else header.get("timestamp", "")
                    )
                    sessions.append(
                        _StoredSession(
                            session_id=sid,
                            title=_session_title(history),
                            _updated_at=_updated_at,
                            history=history,
                            round_usages=round_usages,
                        )
                    )
                except OSError, json.JSONDecodeError, ValueError, KeyError, TypeError:
                    continue
        return sorted(sessions, key=lambda item: item._updated_at, reverse=True)


def _format_relative_time(timestamp: str) -> str:
    _updated_at = datetime.fromisoformat(timestamp)
    now = datetime.now(UTC)
    delta = now - _updated_at.astimezone(UTC)
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


def _format_session_choice(stored: _StoredSession) -> str:
    return f"{stored.title} ({_format_relative_time(stored._updated_at)})"


def _select_session(
    sessions: list[_StoredSession], current_session_id: str | None = None
) -> str | None:
    selected_index = 0
    if current_session_id is not None:
        for i, session in enumerate(sessions):
            if session.session_id == current_session_id:
                selected_index = i
                break
    result = select_from_list(
        sessions,
        "Resume a previous session",
        _format_session_choice,
        selected_index=selected_index,
    )
    return result.session_id if result is not None else None


def prompt_resume(
    manager: SessionManager,
    current_session_id: str,
    history: list[Message],
) -> tuple[str, list[Message], bool]:
    clear_terminal()
    sessions = manager.list_sessions()
    if not sessions:
        print("No saved sessions found.\n")
        return current_session_id, history, False

    result = _select_session(sessions, current_session_id=current_session_id)
    print()

    if result is None:
        print_session_history(history)
        return current_session_id, history, False

    chosen = next(stored for stored in sessions if stored.session_id == result)
    print_session_history(chosen.history)
    token_tracker.restore(chosen.round_usages)
    return chosen.session_id, chosen.history.copy(), True
