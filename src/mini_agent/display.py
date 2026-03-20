import difflib
import shutil
from typing import Any, cast

from .tools import safe_path

RED_BG = "\x1b[48;5;224m\x1b[30m"
GREEN_BG = "\x1b[48;5;194m\x1b[30m"
LIGHT_TEXT = "\x1b[37m"
RESET = "\x1b[0m"


def color_full_line(text: str, color: str) -> str:
    width = shutil.get_terminal_size(fallback=(80, 20)).columns
    return f"{color}{text.ljust(width)}{RESET}"


def format_edit_diff(old_text: str, new_text: str, start_line: int) -> str:
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines)
    formatted_lines = []
    old_line_no = start_line
    new_line_no = start_line

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for old_line, _new_line in zip(
                old_lines[i1:i2], new_lines[j1:j2], strict=True
            ):
                formatted_lines.append(f"{new_line_no}  {old_line}")
                old_line_no += 1
                new_line_no += 1
        elif tag == "delete":
            for old_line in old_lines[i1:i2]:
                formatted_lines.append(
                    color_full_line(f"{old_line_no} - {old_line or ' '}", RED_BG)
                )
                old_line_no += 1
        elif tag == "insert":
            for new_line in new_lines[j1:j2]:
                formatted_lines.append(
                    color_full_line(f"{new_line_no} + {new_line or ' '}", GREEN_BG)
                )
                new_line_no += 1
        elif tag == "replace":
            for old_line in old_lines[i1:i2]:
                formatted_lines.append(
                    color_full_line(f"{old_line_no} - {old_line or ' '}", RED_BG)
                )
                old_line_no += 1
            for new_line in new_lines[j1:j2]:
                formatted_lines.append(
                    color_full_line(f"{new_line_no} + {new_line or ' '}", GREEN_BG)
                )
                new_line_no += 1

    return "\n".join(formatted_lines)


def print_tool_result(name: str, input_data: dict[str, Any], output: str) -> None:
    if name == "read_file":
        print(f"> {name} - {input_data['path']}\n")
        return

    if name == "bash":
        print(
            f"> {name} - {input_data['command']}\n{LIGHT_TEXT}{output[:200]}{RESET}\n"
        )
        return

    if name == "edit_file":
        path = cast(str, input_data["path"])
        old_text = cast(str, input_data["old_text"])
        new_text = cast(str, input_data["new_text"])
        existing_content = safe_path(path).read_text()
        start_line = (
            existing_content[: existing_content.index(old_text)].count("\n") + 1
            if old_text in existing_content
            else 1
        )
        diff = format_edit_diff(old_text, new_text, start_line)
        print(f"> {name} - {path}\n{diff}\n")
        return

    print(f"> {name} - {input_data}\n{output[:200]}\n")
