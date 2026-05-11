import os
import signal
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from anthropic.types import ToolParam

from ..config import WORKDIR
from .skills import skill_loader

TIMEOUT_SECONDS = 120
MAX_OUTPUT = 50000


class BashInterruptedError(Exception):
    def __init__(self, partial_output: str) -> None:
        self.partial_output = partial_output


def _kill_process_tree(proc: subprocess.Popen) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
        )
    else:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)


def _resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    return path.resolve() if path.is_absolute() else (WORKDIR / path_str).resolve()


def run_bash(command: str, on_line: Callable[[str], None] | None = None) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(token in command for token in dangerous):
        return "Error: Dangerous command blocked"

    proc = subprocess.Popen(
        command,
        shell=True,
        cwd=WORKDIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )

    stdout = proc.stdout
    assert stdout is not None
    output_parts: list[str] = []

    def _read() -> None:
        for line in stdout:
            output_parts.append(line)
            if on_line is not None:
                on_line(line)

    reader = threading.Thread(target=_read, daemon=True)
    reader.start()

    try:
        reader.join(timeout=TIMEOUT_SECONDS)
    except KeyboardInterrupt:
        _kill_process_tree(proc)
        reader.join(timeout=1)
        output = "".join(output_parts).strip()
        partial = (
            (output[:MAX_OUTPUT] + "\n\nCommand aborted")
            if output
            else "Command aborted"
        )
        raise BashInterruptedError(partial) from None

    if reader.is_alive():
        _kill_process_tree(proc)
        reader.join(timeout=1)
        output = "".join(output_parts).strip()
        suffix = f"Command timed out after {TIMEOUT_SECONDS} seconds"
        return output[:MAX_OUTPUT] + "\n\n" + suffix if output else suffix

    exit_code = proc.wait()
    output = "".join(output_parts).strip()
    if not output:
        return f"(no output)\n\nCommand exited with code {exit_code}"
    return output[:MAX_OUTPUT]


def run_read(path: str, limit: int | None = None) -> str:
    try:
        text = _resolve_path(path).read_text()
        lines = text.splitlines()
        if limit and limit < len(lines):
            remaining = len(lines) - limit
            lines = lines[:limit] + [f"... ({remaining} more lines)"]
        return "\n".join(lines)[:MAX_OUTPUT]
    except Exception as exc:
        return f"Error: {exc}"


def run_write(path: str, content: str) -> str:
    try:
        file_path = _resolve_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as exc:
        return f"Error: {exc}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        file_path = _resolve_path(path)
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
