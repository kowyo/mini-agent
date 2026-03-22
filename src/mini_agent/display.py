import difflib
import importlib.metadata
from collections.abc import Callable, Iterable
from html import escape
from typing import cast

from anthropic.types import MessageParam
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.data_structures import Point
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.formatted_text.base import StyleAndTextTuples
from prompt_toolkit.layout import controls as pt_controls
from prompt_toolkit.layout import menus as pt_menus
from prompt_toolkit.shortcuts import print_formatted_text
from prompt_toolkit.styles import Style

from .config import MODEL
from .tools import safe_path

COMMANDS = {
    "/new": "Start a new session",
    "/resume": "Resume a previous session",
}

_MENU_ALIGNMENT_PATCHED = False
_MENU_ANCHOR_PATCHED = False


def _patch_completion_menu_alignment() -> None:
    """Remove the built-in one-cell left padding in completion rows."""
    global _MENU_ALIGNMENT_PATCHED

    if _MENU_ALIGNMENT_PATCHED:
        return

    def _aligned_menu_item_fragments(
        completion: Completion,
        is_current_completion: bool,
        width: int,
        space_after: bool = False,
    ) -> StyleAndTextTuples:
        if is_current_completion:
            style_str = (
                f"class:completion-menu.completion.current {completion.style} "
                f"{completion.selected_style}"
            )
        else:
            style_str = "class:completion-menu.completion " + completion.style

        text, text_width = pt_menus._trim_formatted_text(
            completion.display,
            (width - 1 if space_after else width),
        )
        padding = " " * (width - text_width)

        return cast(
            StyleAndTextTuples,
            pt_menus.to_formatted_text(
                [] + text + [("", padding)],
                style=style_str,
            ),
        )

    menu_fragments_fn = cast(
        Callable[[Completion, bool, int, bool], StyleAndTextTuples],
        _aligned_menu_item_fragments,
    )
    menu_attr_name = "_get_menu_item_fragments"
    setattr(pt_menus, menu_attr_name, menu_fragments_fn)
    _MENU_ALIGNMENT_PATCHED = True


def _patch_completion_menu_anchor() -> None:
    """Shift the completion menu anchor to the completion start column."""
    global _MENU_ANCHOR_PATCHED

    if _MENU_ANCHOR_PATCHED:
        return

    original_create_content = pt_controls.BufferControl.create_content

    def _aligned_create_content(
        self: pt_controls.BufferControl,
        width: int,
        height: int,
        preview_search: bool = False,
    ) -> pt_controls.UIContent:
        content = original_create_content(self, width, height, preview_search)

        if self.buffer.complete_state and content.menu_position is not None:
            completion = self.buffer.complete_state.current_completion
            if completion is None and self.buffer.complete_state.completions:
                completion = self.buffer.complete_state.completions[0]

            start_offset = completion.start_position if completion else -1

            # Anchor at completion start, not current cursor, so `/`, `/n`, and
            # `/ne` all align at the same slash column.
            content.menu_position = Point(
                x=max(0, content.menu_position.x + start_offset),
                y=content.menu_position.y,
            )

        return content

    create_content_fn = cast(
        Callable[[pt_controls.BufferControl, int, int, bool], pt_controls.UIContent],
        _aligned_create_content,
    )
    create_content_attr_name = "create_content"
    setattr(pt_controls.BufferControl, create_content_attr_name, create_content_fn)
    _MENU_ANCHOR_PATCHED = True


_patch_completion_menu_alignment()
_patch_completion_menu_anchor()


class CommandCompleter(Completer):
    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        line_text = document.current_line_before_cursor
        text = line_text.lstrip()

        if not text.startswith("/"):
            return

        for cmd, desc in COMMANDS.items():
            if cmd.startswith(text) and text:
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display_meta=desc,
                )


COMPLETION_STYLE = Style.from_dict(
    {
        "completion-menu.completion": "noinherit",
        "completion-menu.completion.current": "noinherit bold",
        "completion-menu.meta.completion": "noinherit",
        "completion-menu.meta.completion.current": "noinherit bold",
        "scrollbar.background": "noinherit",
        "scrollbar.button": "noinherit",
        "scrollbar.arrow-up": "noinherit",
        "scrollbar.arrow-down": "noinherit",
    }
)

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


def print_session_history(history: list[MessageParam]) -> None:
    for message in history:
        content = message["content"]

        if message["role"] == "user" and isinstance(content, str):
            text = content.strip()
            if text:
                lines = text.splitlines() or [""]
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
