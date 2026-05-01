import re
import subprocess
from pathlib import Path
from typing import Any

from anthropic.types import ToolParam

from ..config import WORKDIR
from .skills import skill_loader

BLOCKED_FILE_PATTERNS: list[str] = [
    ".env",
    "id_ed25519",
    "authorized_keys",
    "known_hosts",
]


def safe_path(path_str: str) -> Path:
    path = Path(path_str)
    path = path.resolve() if path.is_absolute() else (WORKDIR / path_str).resolve()

    if path.is_relative_to(WORKDIR.resolve()) or path.is_relative_to(
        Path("/tmp").resolve()
    ):
        return path

    raise ValueError(f"Path escapes workspace: {path_str}")


def _check_blocked(path: Path) -> None:
    for pattern in BLOCKED_FILE_PATTERNS:
        if pattern in path.name:
            raise ValueError(f"'{path.name}' is blocked for security reasons")


def _check_write_target(path_str: str) -> str | None:
    if path_str.startswith("/dev/"):
        return None
    if path_str.startswith(("/tmp", WORKDIR.as_posix())):
        return None
    try:
        safe_path(path_str)
        return None
    except ValueError:
        return f"<system-reminder>\nError: blocked — writes to path outside workspace: {path_str}\n</system-reminder>"


def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot"]
    for token in dangerous:
        if token in command:
            return f"<system-reminder>\nError: dangerous command blocked (matched: {token!r})\n</system-reminder>"

    for pattern in BLOCKED_FILE_PATTERNS:
        if pattern in command:
            return f"<system-reminder>\nError: command references blocked file pattern '{pattern}'\n</system-reminder>"

    match = re.search(r"(?:[&\d]*>+)\s*/dev/(\w+)", command)
    if match and match.group(1) != "null":
        return f"<system-reminder>\nError: dangerous command blocked (matched: /dev/{match.group(1)})\n</system-reminder>"

    for match in re.finditer(r"(?:^|[\s|&;])[\w]*>+\s*(/[\w./-]+)", command):
        err = _check_write_target(match.group(1))
        if err:
            return err

    for match in re.finditer(r"\btee\s+(/[\w./-]+)", command):
        err = _check_write_target(match.group(1))
        if err:
            return err

    for match in re.finditer(r"\bdd\s+.*?of=(/[\w./-]+)", command):
        err = _check_write_target(match.group(1))
        if err:
            return err

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return "<system-reminder>\nError: timeout (120s)\n</system-reminder>"

    output = (result.stdout + result.stderr).strip()
    return output[:50000] if output else "(no output)"


def run_read(path: str, limit: int | None = None) -> str:
    try:
        file_path = safe_path(path)
        _check_blocked(file_path)
        text = file_path.read_text()
        lines = text.splitlines()
        if limit and limit < len(lines):
            remaining = len(lines) - limit
            lines = lines[:limit] + [f"... ({remaining} more lines)"]
        return "\n".join(lines)[:50000]
    except Exception as exc:
        return f"Error: {exc}"


def run_write(path: str, content: str) -> str:
    try:
        file_path = safe_path(path)
        _check_blocked(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as exc:
        return f"Error: {exc}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        file_path = safe_path(path)
        _check_blocked(file_path)
        content = file_path.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        file_path.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as exc:
        return f"Error: {exc}"


TOOL_HANDLERS: dict[str, Any] = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "activate_skill": lambda **kw: skill_loader.get_content(kw["name"]),
}

TOOLS: list[ToolParam] = [
    {
        "name": "bash",
        "description": "Run a shell command.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read file contents.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace exact text in a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "activate_skill",
        "description": "Load specialized knowledge by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill name to load"}
            },
            "required": ["name"],
        },
    },
]
