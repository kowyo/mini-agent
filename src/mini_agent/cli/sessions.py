import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

lazy from anthropic.types import MessageParam
lazy from pydantic import BaseModel

from ..config import SESSION_DIR, config
from .clipboard import extract_text_content
from .display.picker import select_from_list
from .terminal import clear_terminal
from .token import Usage, token_tracker
lazy from .display.printing import print_session_history

type History = list[MessageParam]


@dataclass
class _StoredSession:
    session_id: str
    title: str
    _updated_at: str
    history: History
    round_usages: list[Usage]
    total_usage: Usage | None


def _serialize_content(content: str | Iterable[object]) -> list[object]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    serialized_blocks: list[object] = []
    for block in content:
        if isinstance(block, BaseModel):
            dumped = block.model_dump(mode="json", exclude_none=True)
            dumped.pop("parsed_output", None)
            serialized_blocks.append(dumped)
        else:
            serialized_blocks.append(block)
    return serialized_blocks


def _format_timestamp(now: datetime) -> str:
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _usage_to_dict(usage: Usage) -> dict[str, int]:
    return {
        "input_tokens": usage.input_tokens,
        "cache_creation_input_tokens": usage.cache_creation_input_tokens,
        "cache_read_input_tokens": usage.cache_read_input_tokens,
        "output_tokens": usage.output_tokens,
    }


def _usage_from_dict(usage: dict[str, Any]) -> Usage:
    return Usage(
        input_tokens=usage.get("input_tokens", 0),
        cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
        cache_read_input_tokens=usage.get("cache_read_input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
    )


def _has_prefix(history: History, stored: History) -> bool:
    if len(stored) > len(history):
        return False
    for stored_message, message in zip(stored, history, strict=False):
        if stored_message["role"] != message["role"]:
            return False
        if _serialize_content(stored_message["content"]) != _serialize_content(
            message["content"]
        ):
            return False
    return True


def _session_title(history: History) -> str:
    for message in history:
        if message["role"] == "user":
            text = extract_text_content(message["content"])
            title = " ".join(text.splitlines()).strip()
            if title:
                return title[:60]
    return "Untitled session"


class SessionManager:
    _VERSION = 1

    def __init__(self, session_dir: Path | None = None) -> None:
        self._base_dir = session_dir or SESSION_DIR

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid7())

    @staticmethod
    def _entry_id() -> str:
        return uuid.uuid4().hex[:8]

    @staticmethod
    def _message_body(
        message: MessageParam, now: datetime, usage: Usage | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "role": message["role"],
            "content": _serialize_content(message["content"]),
            "timestamp": int(now.timestamp() * 1000),
        }
        if message["role"] == "assistant":
            body["model"] = config.get_model()
            if usage is not None:
                body["usage"] = {
                    "input_tokens": usage.input_tokens,
                    "cache_creation_input_tokens": usage.cache_creation_input_tokens,
                    "cache_read_input_tokens": usage.cache_read_input_tokens,
                    "output_tokens": usage.output_tokens,
                }
        return body

    @staticmethod
    def _decode_entries(
        entries: list[dict[str, Any]],
    ) -> tuple[History, list[Usage], int]:
        history: History = []
        round_usages: list[Usage] = []
        max_ts = 0
        for entry in entries:
            message = entry.get("message")
            if not isinstance(message, dict):
                continue
            if entry.get("type") == "compact":
                history.clear()
                round_usages.clear()
            history.append({"role": message["role"], "content": message["content"]})
            max_ts = max(max_ts, message.get("timestamp", 0))
            usage = message.get("usage")
            if message["role"] == "assistant" and isinstance(usage, dict):
                round_usages.append(_usage_from_dict(usage))
        return history, round_usages, max_ts

    def _cwd_dir(self, cwd: str | None = None) -> Path:
        cwd = cwd or str(Path.cwd())
        resolved = str(Path(cwd).resolve())
        safe = resolved.lstrip("/").replace("/", "-").replace(":", "-")
        return self._base_dir / (safe or "__root__")

    def _find_file(self, session_id: str) -> Path | None:
        if not self._base_dir.exists():
            return None
        for cwd_dir in self._base_dir.iterdir():
            if not cwd_dir.is_dir():
                continue
            for f in cwd_dir.glob(f"*_{session_id}.jsonl"):
                return f
        return None

    def exists(self, session_id: str) -> bool:
        return self._find_file(session_id) is not None

    def save(
        self,
        session_id: str,
        history: History,
        round_usages: list[Usage] | None = None,
        cwd: str | None = None,
        total_usage: Usage | None = None,
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

        stored_history, _, _ = self._decode_entries(entries[1:])
        rewrote = not _has_prefix(history, stored_history)

        if rewrote and history:
            now = datetime.now(UTC)
            entries.append(
                {
                    "type": "compact",
                    "id": self._entry_id(),
                    "timestamp": _format_timestamp(now),
                    "message": self._message_body(history[0], now),
                }
            )
            save_start = 1
            saved_asst = 0
        else:
            save_start = len(stored_history)
            saved_asst = sum(1 for m in stored_history if m["role"] == "assistant")

        for message in history[save_start:]:
            now = datetime.now(UTC)
            usage = None
            if (
                message["role"] == "assistant"
                and round_usages
                and saved_asst < len(round_usages)
            ):
                usage = round_usages[saved_asst]
                saved_asst += 1
            entries.append(
                {
                    "type": "message",
                    "id": self._entry_id(),
                    "timestamp": _format_timestamp(now),
                    "message": self._message_body(message, now, usage),
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
                "title": _session_title(history),
            }
            if total_usage is not None:
                header["total_usage"] = _usage_to_dict(total_usage)
            file_timestamp = ts.replace(":", "-").replace(".", "-")
            path = session_dir / f"{file_timestamp}_{session_id}.jsonl"
            entries.insert(0, header)

        if total_usage is not None:
            entries[0]["total_usage"] = _usage_to_dict(total_usage)

        path.write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n"
        )

    def load(self, session_id: str) -> tuple[History, list[Usage]]:
        path = self._find_file(session_id)
        if path is None:
            return [], []

        lines = [line for line in path.read_text().splitlines() if line.strip()]
        entries: list[dict[str, Any]] = []
        for line in lines[1:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        history, round_usages, _ = self._decode_entries(entries)
        return history, round_usages

    def list_sessions(self) -> list[_StoredSession]:
        if not self._base_dir.exists():
            return []
        sessions: list[_StoredSession] = []
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
                    entries = [json.loads(line) for line in lines[1:]]
                    history, round_usages, max_ts = self._decode_entries(entries)
                    updated_at = (
                        datetime.fromtimestamp(max_ts / 1000, UTC).isoformat()
                        if max_ts
                        else header.get("timestamp", "")
                    )
                    stored_usage = header.get("total_usage")
                    sessions.append(
                        _StoredSession(
                            session_id=sid,
                            title=header.get("title") or _session_title(history),
                            _updated_at=updated_at,
                            history=history,
                            round_usages=round_usages,
                            total_usage=(
                                _usage_from_dict(stored_usage)
                                if isinstance(stored_usage, dict)
                                else None
                            ),
                        )
                    )
                except OSError, json.JSONDecodeError, ValueError, KeyError:
                    continue
        return sorted(sessions, key=lambda item: item._updated_at, reverse=True)


def _format_relative_time(timestamp: str) -> str:
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
    history: History,
) -> tuple[str, History, bool]:
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
    token_tracker.restore(chosen.round_usages, chosen.total_usage)
    return chosen.session_id, chosen.history.copy(), True
