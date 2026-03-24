import os
import subprocess
from html import escape
from typing import cast

from anthropic.types import MessageParam
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import print_formatted_text

from ...agent.tools import safe_path
from ...config import CLI_NAME, CLI_VERSION, get_model
from .diff import LIGHT_TEXT, RESET, format_edit_diff


def clear_terminal() -> None:
    subprocess.run(
        ["cls" if os.name == "nt" else "clear"],
        check=False,
        shell=os.name == "nt",
    )


def print_welcome_banner() -> None:
    lines = [
        f" >_ {CLI_NAME} (v{CLI_VERSION})",
        "",
        f" model: {get_model()}",
    ]
    width = max(len(line) for line in lines)

    print(f"╭{'─' * (width + 2)}╮")
    for line in lines:
        print(f"│ {line.ljust(width)} │")
    print(f"╰{'─' * (width + 2)}╯\n")


def print_session_history(history: list[MessageParam]) -> None:
    for message in history:
        content = message["content"]

        if message["role"] == "user" and isinstance(content, str):
            text = content.strip()
            if text:
                lines = text.splitlines()
                print_formatted_text(
                    HTML(f'<style color="#87CEEB">&gt; </style>{escape(lines[0])}')
                )
                for line in lines[1:]:
                    print(line)
                print()
            continue

        if message["role"] == "assistant" and isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = str(block.get("text", "")).strip()
                    if text:
                        print(f"> {text}\n")


def print_tool_result(name: str, input_data: dict[str, object], output: str) -> None:
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
