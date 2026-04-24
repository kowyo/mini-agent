import os
import subprocess
from html import escape
from typing import cast

from anthropic.types import MessageParam
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import print_formatted_text
from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

from ...agent.tools import safe_path
from ...config import DISTRIBUTION_NAME, DISTRIBUTION_VERSION, config
from ..clipboard import extract_text_content
from .box import print_box
from .diff import format_edit_diff
from .theme import LIGHT_HINT_STYLE_RICH, PROMPT_TOOLKIT_ACCENT_COLOR

console = Console()


def clear_terminal() -> None:
    subprocess.run(
        ["cls" if os.name == "nt" else "clear"],
        check=False,
        shell=os.name == "nt",
    )


def clear_prompt_line() -> None:
    print("\r\033[2K\033[1A\033[2K\r", end="", flush=True)


def print_welcome_banner() -> None:
    version_line = Text.assemble(
        f" >_ {DISTRIBUTION_NAME} ",
        (f"(v{DISTRIBUTION_VERSION})", LIGHT_HINT_STYLE_RICH),
    )
    lines = [
        version_line,
        "",
        f" model: {config.get_model()} {config.get_reasoning_effort()}",
    ]
    print_box(console, lines)
    print()


def print_session_history(history: list[MessageParam]) -> None:
    clear_terminal()
    print_welcome_banner()
    for message in history:
        content = message["content"]

        if message["role"] == "user":
            text = extract_text_content(content)
            if text:
                lines = text.splitlines()
                print_formatted_text(
                    HTML(
                        f'<style color="{PROMPT_TOOLKIT_ACCENT_COLOR}">&gt; </style>{escape(lines[0])}'
                    )
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
                        console.print(Markdown(text))
                        print()


def print_tool_start(name: str, input_data: dict[str, object]) -> None:
    """Print tool name and input before executing the tool."""
    if name == "read_file":
        print(f"> {name} - {input_data['path']}")
        return

    if name == "write_file":
        print(f"> {name} - [{input_data['path']}]")
        return

    if name == "bash":
        print(f"> {name} - {input_data['command']}")
        return

    if name == "edit_file":
        print(f"> {name} - {input_data['path']}")
        return

    if name == "activate_skill":
        print(f"> {name} - {input_data['name']}")
        return

    print(f"> {name} - {input_data}")


def print_tool_result(name: str, input_data: dict[str, object], output: str) -> None:
    """Print tool output after execution."""
    if name == "bash":
        text = Text.from_ansi(output)
        text.stylize(LIGHT_HINT_STYLE_RICH)
        console.print(text)
        print()
        return

    if name == "edit_file":
        path = cast(str, input_data["path"])
        if output.startswith("Error"):
            print(f"{output}\n")
            return
        old_text = cast(str, input_data["old_text"])
        new_text = cast(str, input_data["new_text"])
        edited_content = safe_path(path).read_text()
        pos = edited_content.find(new_text)
        start_line = edited_content[:pos].count("\n") + 1 if pos != -1 else 1
        diff = format_edit_diff(old_text, new_text, start_line)
        print(f"{diff}\n")
        return

    if name in ("read_file", "write_file", "activate_skill"):
        print()
        return

    print(f"{output[:200]}\n")
