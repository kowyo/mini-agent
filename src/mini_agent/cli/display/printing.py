import os
import subprocess
from html import escape
from pathlib import Path
from typing import cast

from anthropic.types import MessageParam
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import print_formatted_text
from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

from ...config import DISTRIBUTION_NAME, DISTRIBUTION_VERSION, config
from ..clipboard import extract_text_content
from .box import print_box
from .diff import format_edit_diff
from .theme import (
    LIGHT_HINT_STYLE_RICH,
    PROMPT_TOOLKIT_ACCENT_COLOR,
    THINKING_STYLE_RICH,
)

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
        Text(f" model: {config.get_model()} {config.get_reasoning_effort()}"),
    ]
    print_box(console, lines)


def print_session_history(history: list[MessageParam]) -> None:
    clear_terminal()
    print_welcome_banner()

    tool_registry: dict[str, tuple[str, dict[str, object]]] = {}

    for message in history:
        content = message["content"]

        if message["role"] == "user":
            if isinstance(content, list):
                tool_results = [
                    b
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "tool_result"
                ]
                if tool_results:
                    for block in tool_results:
                        tool_use_id = str(block.get("tool_use_id", ""))
                        name, input_data = tool_registry.get(
                            tool_use_id, ("unknown", {})
                        )
                        output = str(block.get("content", ""))
                        if name == "bash" and output:
                            for line in output.splitlines():
                                text = Text.from_ansi(line.rstrip("\n\r"))
                                text.stylize(LIGHT_HINT_STYLE_RICH)
                                console.print(text)
                            print()
                        else:
                            print_tool_result(name, input_data, output)

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
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text = str(block.get("text", "")).strip()
                    if text:
                        console.print(Markdown(text))
                        print()
                elif block.get("type") == "thinking":
                    thinking_text = str(block.get("thinking", "")).strip()
                    if thinking_text:
                        console.print(
                            Markdown(thinking_text, style=THINKING_STYLE_RICH)
                        )
                        print()
                elif block.get("type") == "tool_use":
                    name = str(block.get("name", "unknown"))
                    input_data = cast(dict[str, object], block.get("input", {}))
                    tool_use_id = str(block.get("id", ""))
                    if tool_use_id:
                        tool_registry[tool_use_id] = (name, input_data)
                    print_tool_start(name, input_data)


def print_tool_start(name: str, input_data: dict[str, object]) -> None:
    """Print tool name and input before executing the tool."""
    if name == "read_file":
        text = Text(f"> {name} - {input_data['path']}")
        offset = input_data.get("offset")
        limit = input_data.get("limit")
        if offset is not None or limit is not None:
            hints = []
            if offset is not None:
                hints.append(f"offset {offset}")
            if limit is not None:
                hints.append(f"limit {limit}")
            text.append(f" ({', '.join(hints)})", style=LIGHT_HINT_STYLE_RICH)
        console.print(text)
        return

    if name == "write_file":
        print(f"> {name} - [{input_data['path']}]")
        return

    if name == "bash":
        text = Text(f"> {name} - {input_data['command']}")
        timeout = input_data.get("timeout")
        if timeout is not None:
            text.append(f" (timeout {timeout}s)", style=LIGHT_HINT_STYLE_RICH)
        console.print(text)
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
        console.print()
        return

    if name == "edit_file":
        path = cast(str, input_data["path"])
        if output.startswith("Error"):
            print(f"{output}\n")
            return
        old_text = cast(str, input_data["old_text"])
        new_text = cast(str, input_data["new_text"])
        try:
            edited_content = Path(path).read_text()
            pos = edited_content.find(new_text)
            start_line = edited_content[:pos].count("\n") + 1 if pos != -1 else 1
            diff = format_edit_diff(old_text, new_text, start_line)
            print(f"{diff}\n")
        except FileNotFoundError:
            print(f"> {name} - {path} (file no longer available)\n")
        return

    if name in ("read_file", "write_file", "activate_skill"):
        print()
        return

    print(f"{output[:200]}\n")
