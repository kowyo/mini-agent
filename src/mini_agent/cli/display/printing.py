import os
import subprocess
from pathlib import Path
from typing import Any, cast

from anthropic.types import MessageParam
from pydantic import BaseModel
from rich.cells import chop_cells
from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

from ...config import DISTRIBUTION_NAME, DISTRIBUTION_VERSION, config
from ..clipboard import extract_text_content
from .box import print_box
from .diff import format_edit_diff
from .terminal_image import render_image
from .theme import (
    ACCENT_COLOR,
    LIGHT_HINT_STYLE_RICH,
    THINKING_STYLE_RICH,
)

_console = Console()

_TOOL_RESULT_PREVIEW_LINES = 10

_full_tool_output = False


def toggle_full_tool_output() -> bool:
    global _full_tool_output
    _full_tool_output = not _full_tool_output
    return _full_tool_output


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
    print_box(_console, lines)


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
                        raw_content = block.get("content", "")
                        output = (
                            raw_content
                            if isinstance(raw_content, list)
                            else str(raw_content)
                        )
                        if name == "bash" and isinstance(output, str) and output:
                            for line in output.splitlines():
                                text = Text.from_ansi(line.rstrip("\n\r"))
                                text.stylize(LIGHT_HINT_STYLE_RICH)
                                _console.print(text)
                            print()
                        else:
                            print_tool_result(name, input_data, output)

            text = extract_text_content(content)
            if text:
                lines = text.splitlines()
                _console.print(
                    Text.assemble(("> ", ACCENT_COLOR), lines[0]), highlight=False
                )
                for line in lines[1:]:
                    print(line)
                print()
            continue

        if message["role"] == "assistant" and isinstance(content, list):
            for raw_block in content:
                block = (
                    raw_block.model_dump()
                    if isinstance(raw_block, BaseModel)
                    else raw_block
                )
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text = str(block.get("text", "")).strip()
                    if text:
                        _console.print(Markdown(text))
                        print()
                elif block.get("type") == "thinking":
                    thinking_text = str(block.get("thinking", "")).strip()
                    if thinking_text:
                        _console.print(
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
        _console.print(text)
        return

    if name == "write_file":
        print(f"> {name} - [{input_data['path']}]")
        return

    if name == "bash":
        text = Text(f"> {name} - {input_data['command']}")
        timeout = input_data.get("timeout")
        if timeout is not None:
            text.append(f" (timeout {timeout}s)", style=LIGHT_HINT_STYLE_RICH)
        _console.print(text)
        return

    if name == "edit_file":
        print(f"> {name} - {input_data['path']}")
        return

    if name == "activate_skill":
        print(f"> {name} - {input_data['name']}")
        return

    print(f"> {name} - {input_data}")


def print_tool_result(
    name: str, input_data: dict[str, object], output: str | list[Any]
) -> None:
    """Print tool output after execution."""
    if name == "bash":
        _console.print()
        return

    if name == "edit_file":
        path = cast(str, input_data["path"])
        if isinstance(output, str) and output.startswith("Error"):
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
        if name == "read_file" and isinstance(output, list):
            output_str, images = _split_tool_output(output)
            print(output_str)
            for image in images:
                print(image)
        print()
        return

    output_str, images = _split_tool_output(output)
    if output_str or not images:
        if _full_tool_output:
            print(output_str)
        else:
            _print_tool_output_preview(output_str)
    for image in images:
        print(image)
    print()


def _print_tool_output_preview(output_str: str) -> None:
    visual_lines = [
        chunk
        for line in output_str.splitlines()
        for chunk in chop_cells(line, _console.width) or [""]
    ]
    print("\n".join(visual_lines[:_TOOL_RESULT_PREVIEW_LINES]))
    hidden_lines = len(visual_lines) - _TOOL_RESULT_PREVIEW_LINES
    if hidden_lines > 0:
        _console.print(
            f"… ({hidden_lines} more lines, ctrl+o to expand)",
            style=LIGHT_HINT_STYLE_RICH,
        )


def _split_tool_output(output: str | list[Any]) -> tuple[str, list[str]]:
    if isinstance(output, str):
        return output, []
    texts: list[str] = []
    images: list[str] = []
    for block in output:
        source = block.get("source", {})
        if block.get("type") == "text":
            texts.append(str(block.get("text", "")))
        elif block.get("type") == "image" and (
            image := render_image(source["data"], _console.width)
        ):
            images.append(image)
        else:
            texts.append(f"[{source.get('media_type', block.get('type'))}]")
    return "\n".join(texts), images
