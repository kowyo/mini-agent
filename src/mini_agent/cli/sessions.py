import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from anthropic.types import MessageParam
from pydantic import BaseModel

from ..config import SESSION_DIR
from .clipboard import extract_text_content
from .display import clear_terminal, print_session_history
from .display.picker import select_from_list
from .token import Usage, token_tracker


@dataclass
class StoredSession:
    session_id: str
    title: str
    updated_at: str
    history: list[MessageParam]
    last_usage: Usage


def serialize_content(content: str | Iterable[object]) -> str | list[object]:
    """Serialize message content blocks for JSON output."""
    if isinstance(content, str):
        return content
    serialized_blocks: list[object] = []
    for block in content:
        if isinstance(block, BaseModel):
            dumped = block.model_dump(mode="json", exclude_none=True)
            dumped.pop("parsed_output", None)
            serialized_blocks.append(dumped)
        else:
            serialized_blocks.append(block)
    return serialized_blocks


def session_title(history: list[MessageParam]) -> str:
    """Derive a display title from the first user message."""
    for message in history:
        if message["role"] == "user":
            text = extract_text_content(message["content"])
            title = " ".join(text.splitlines()).strip()
            if title:
                return title[:60]
    return "Untitled session"


class SessionManager:
    """Manages session files in the --<cwd>--/<timestamp>_<uuidv7>.jsonl format."""

    VERSION = 2

    def __init__(self, session_dir: Path | None = None) -> None:
        """Initialize with an optional base directory (defaults to SESSION_DIR)."""
        self._base_dir = session_dir or SESSION_DIR

    @staticmethod
    def new_id() -> str:
        """Generate a new UUIDv7 session identifier."""
        return str(uuid.uuid7())

    @staticmethod
    def entry_id() -> str:
        """Generate an 8-char hex entry ID."""
        return uuid.uuid4().hex[:8]

    def cwd_dir(self, cwd: str | None = None) -> Path:
        """Return the encoded-cwd subdirectory for the given working directory."""
        cwd = cwd or str(Path.cwd())
        resolved = str(Path(cwd).resolve())
        safe = resolved.lstrip("/").replace("/", "-").replace(":", "-")
        return self._base_dir / f"--{safe}--"

    def find_file(self, session_id: str) -> Path | None:
        """Find a session file by its ID across all cwd subdirectories."""
        if not self._base_dir.exists():
            return None
        for cwd_dir in self._base_dir.iterdir():
            if not cwd_dir.is_dir():
                continue
            for f in cwd_dir.glob(f"*_{session_id}.jsonl"):
                return f
        return None

    def exists(self, session_id: str) -> bool:
        """Return True if a session file with the given ID exists."""
        return self.find_file(session_id) is not None

    def save(
        self,
        session_id: str,
        history: list[MessageParam],
        usage: Usage,
        cwd: str | None = None,
    ) -> None:
        """Save or append to a session file, preserving existing entry IDs/timestamps."""
        cwd = cwd or str(Path.cwd())
        session_dir = self.cwd_dir(cwd)
        session_dir.mkdir(parents=True, exist_ok=True)

        existing = self.find_file(session_id)
        if existing:
            lines = [line for line in existing.read_text().splitlines() if line.strip()]
            saved = len(lines) - 2  # header + old usage
            lines = lines[:-1]  # drop old usage, will append new one
        else:
            lines = []
            saved = 0

        for message in history[saved:]:
            now = datetime.now(UTC)
            entry_ts = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            lines.append(
                json.dumps(
                    {
                        "type": "message",
                        "id": self.entry_id(),
                        "timestamp": entry_ts,
                        "message": {
                            "role": message["role"],
                            "content": serialize_content(message["content"]),
                            "timestamp": int(now.timestamp() * 1000),
                        },
                    }
                )
            )

        # Replace usage line (append if new session, overwrite if existing)
        lines.append(
            json.dumps(
                {
                    "input_tokens": usage.input_tokens,
                    "cache_creation_input_tokens": usage.cache_creation_input_tokens,
                    "cache_read_input_tokens": usage.cache_read_input_tokens,
                    "output_tokens": usage.output_tokens,
                }
            )
        )

        if existing:
            path = existing
        else:
            now = datetime.now(UTC)
            ts = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            header = {
                "type": "session",
                "version": self.VERSION,
                "id": session_id,
                "timestamp": ts,
                "cwd": cwd,
            }
            file_timestamp = ts.replace(":", "-").replace(".", "-")
            path = session_dir / f"{file_timestamp}_{session_id}.jsonl"
            lines.insert(0, json.dumps(header))

        path.write_text("\n".join(lines) + "\n")

    def load(self, session_id: str) -> tuple[list[MessageParam], Usage]:
        """Load a session file and return (history, usage)."""
        path = self.find_file(session_id)
        if path is None:
            return [], Usage(0, 0, 0, 0)

        lines = [line for line in path.read_text().splitlines() if line.strip()]
        *entry_lines, usage_line = lines[1:]
        record = json.loads(usage_line)
        usage = Usage(
            input_tokens=record.get("input_tokens", 0),
            cache_creation_input_tokens=record.get("cache_creation_input_tokens", 0),
            cache_read_input_tokens=record.get("cache_read_input_tokens", 0),
            output_tokens=record.get("output_tokens", 0),
        )
        history: list[MessageParam] = []
        for line in entry_lines:
            entry = json.loads(line)
            msg = entry["message"]
            history.append({"role": msg["role"], "content": msg["content"]})
        return history, usage

    def list_sessions(self) -> list[StoredSession]:
        """Return all stored sessions sorted by most recently modified."""
        if not self._base_dir.exists():
            return []
        sessions: list[StoredSession] = []
        for cwd_dir in self._base_dir.iterdir():
            if not cwd_dir.is_dir():
                continue
            for path in cwd_dir.glob("*.jsonl"):
                try:
                    content = path.read_text()
                    lines = [line for line in content.splitlines() if line.strip()]
                    if not lines:
                        continue
                    header = json.loads(lines[0])
                    if header.get("type") != "session":
                        continue
                    sid = header.get("id", "")
                    if not sid:
                        continue
                    *entry_lines, usage_line = lines[1:]
                    record = json.loads(usage_line)
                    usage = Usage(
                        input_tokens=record.get("input_tokens", 0),
                        cache_creation_input_tokens=record.get(
                            "cache_creation_input_tokens", 0
                        ),
                        cache_read_input_tokens=record.get(
                            "cache_read_input_tokens", 0
                        ),
                        output_tokens=record.get("output_tokens", 0),
                    )
                    max_ts = 0
                    history: list[MessageParam] = []
                    for line in entry_lines:
                        entry = json.loads(line)
                        msg = entry["message"]
                        history.append({"role": msg["role"], "content": msg["content"]})
                        ts = msg.get("timestamp", 0)
                        if ts > max_ts:
                            max_ts = ts
                    updated_at = (
                        datetime.fromtimestamp(max_ts / 1000, UTC).isoformat()
                        if max_ts
                        else header.get("timestamp", "")
                    )
                    sessions.append(
                        StoredSession(
                            session_id=sid,
                            title=session_title(history),
                            updated_at=updated_at,
                            history=history,
                            last_usage=usage,
                        )
                    )
                except OSError, json.JSONDecodeError, ValueError, KeyError:
                    continue
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)


def format_relative_time(timestamp: str) -> str:
    """Format an ISO timestamp as a human-readable relative time string."""
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
    """Format a StoredSession for display in the session picker."""
    return f"{stored.title} ({format_relative_time(stored.updated_at)})"


def select_session(
    sessions: list[StoredSession], current_session_id: str | None = None
) -> str | None:
    """Show an interactive picker and return the selected session ID, or None."""
    selected_index = 0
    if current_session_id is not None:
        for i, session in enumerate(sessions):
            if session.session_id == current_session_id:
                selected_index = i
                break
    result = select_from_list(
        sessions,
        "Resume a previous session",
        format_session_choice,
        selected_index=selected_index,
    )
    return result.session_id if result is not None else None


def prompt_resume(
    manager: SessionManager,
    current_session_id: str,
    history: list[MessageParam],
) -> tuple[str, list[MessageParam], bool]:
    """Show the session picker and return (session_id, history, resumed)."""
    clear_terminal()
    sessions = manager.list_sessions()
    if not sessions:
        print("No saved sessions found.\n")
        return current_session_id, history, False

    result = select_session(sessions, current_session_id=current_session_id)
    print()

    if result is None:
        print_session_history(history)
        return current_session_id, history, False

    chosen = next(stored for stored in sessions if stored.session_id == result)
    print_session_history(chosen.history)
    token_tracker.restore(chosen.last_usage)
    return chosen.session_id, chosen.history.copy(), True
