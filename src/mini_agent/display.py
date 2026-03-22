import difflib
import importlib.metadata
from typing import Any, cast

from .config import MODEL
from .tools import safe_path

CLI_NAME = "mini-agent"
CLI_VERSION = importlib.metadata.version(CLI_NAME)

RED_BG = "\x1b[48;5;224m\x1b[30m"
GREEN_BG = "\x1b[48;5;194m\x1b[30m"
LIGHT_TEXT = "\x1b[37m"
RESET = "\x1b[0m"


def color_full_line(text: str, color: str) -> str:
    return f"{color}{text}\x1b[K{RESET}"


def format_edit_diff(old_text: str, new_text: str, start_line: int) -> str:
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines)
    formatted_lines: list[str] = []
    old_line_no = start_line
    new_line_no = start_line

    def append_deletions(lines: list[str]) -> None:
        nonlocal old_line_no
        for line in lines:
            formatted_lines.append(
                color_full_line(f"{old_line_no} - {line or ' '}", RED_BG)
            )
            old_line_no += 1

    def append_insertions(lines: list[str]) -> None:
        nonlocal new_line_no
        for line in lines:
            formatted_lines.append(
                color_full_line(f"{new_line_no} + {line or ' '}", GREEN_BG)
            )
            new_line_no += 1

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for old_line, _new_line in zip(
                old_lines[i1:i2], new_lines[j1:j2], strict=True
            ):
                formatted_lines.append(f"{new_line_no}  {old_line}")
                old_line_no += 1
                new_line_no += 1
        elif tag == "delete":
            append_deletions(old_lines[i1:i2])
        elif tag == "insert":
            append_insertions(new_lines[j1:j2])
        elif tag == "replace":
            append_deletions(old_lines[i1:i2])
            append_insertions(new_lines[j1:j2])

    return "\n".join(formatted_lines)


def print_welcome_banner() -> None:
    lines = [
        f" >_ {CLI_NAME} (v{CLI_VERSION})",
        "",
        f" model:     {MODEL}",
    ]
    width = max(len(line) for line in lines)

    print(f"╭{'─' * (width + 2)}╮")
    for line in lines:
        print(f"│ {line.ljust(width)} │")
    print(f"╰{'─' * (width + 2)}╯\n")


def print_tool_result(name: str, input_data: dict[str, Any], output: str) -> None:
    if name == "read_file":
        print(f"> {name} - {input_data['path']}\n")
        return

    if name == "write_file":
        print(f"> {name} - [{input_data['path']}]\n")
        return

    if name == "bash":
        print(
            f"> {name} - {input_data['command']}\n{LIGHT_TEXT}{output[:200]}{RESET}\n"
        )
        return

    if name == "edit_file":
        path = cast(str, input_data["path"])
        if output.startswith("Error"):
            print(f"> {name} - {path}\n{output}\n")
            return
        old_text = cast(str, input_data["old_text"])
        new_text = cast(str, input_data["new_text"])
        edited_content = safe_path(path).read_text()
        pos = edited_content.find(new_text)
        start_line = edited_content[:pos].count("\n") + 1 if pos != -1 else 1
        diff = format_edit_diff(old_text, new_text, start_line)
        print(f"> {name} - {path}\n{diff}\n")
        return

    if name == "todo":
        print(f"> {name}\n{output[:200]}\n")
        return

    print(f"> {name} - {input_data}\n{output[:200]}\n")
