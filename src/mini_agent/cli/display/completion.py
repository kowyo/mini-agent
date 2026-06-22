import re
import subprocess
from collections.abc import Callable, Iterable
from typing import cast

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.data_structures import Point
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text.base import StyleAndTextTuples
from prompt_toolkit.layout import controls as pt_controls
from prompt_toolkit.layout import menus as pt_menus
from prompt_toolkit.styles import Style

from .theme import PROMPT_TOOLKIT_ACCENT_COLOR

COMMANDS = {
    "/new": "Start a new session",
    "/resume": "Resume a previous session",
    "/model": "Select a model",
    "/copy": "Copy the last assistant response to clipboard",
    "/status": "Show current session configuration and token usage",
    "/exit": "exit the session",
}


def _patch_completion_menu_alignment() -> None:
    """Remove the built-in one-cell left padding in completion rows."""

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


def _patch_completion_menu_anchor() -> None:
    original_create_content = pt_controls.BufferControl.create_content

    def _aligned_create_content(
        self: pt_controls.BufferControl,
        width: int,
        height: int,
        preview_search: bool = False,
    ) -> pt_controls.UIContent:
        content = original_create_content(self, width, height, preview_search)

        if self.buffer.complete_state and content.menu_position is not None:
            content.menu_position = Point(
                x=0,
                y=content.menu_position.y,
            )

        return content

    create_content_fn = cast(
        Callable[[pt_controls.BufferControl, int, int, bool], pt_controls.UIContent],
        _aligned_create_content,
    )
    create_content_attr_name = "create_content"
    setattr(pt_controls.BufferControl, create_content_attr_name, create_content_fn)


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


class FileCompleter(Completer):
    _AT_PATTERN = re.compile(r"@([\w.\-/]*)$")
    _MAX_RESULTS = 20

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        text = document.current_line_before_cursor

        match = self._AT_PATTERN.search(text)
        if not match:
            return

        query = match.group(1)
        full_match = match.group(0)

        fd_query = query if query else "."

        try:
            result = subprocess.run(
                [
                    "fd",
                    "--type",
                    "f",
                    "--type",
                    "d",
                    "--full-path",
                    "-i",
                    "--max-depth",
                    "8",
                    fd_query,
                ],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
        except subprocess.TimeoutExpired, FileNotFoundError, OSError:
            return

        if result.returncode != 0:
            return

        files = result.stdout.strip().split("\n")
        if not files or (len(files) == 1 and not files[0]):
            return

        for file_path in files[: self._MAX_RESULTS]:
            if file_path:
                yield Completion(
                    file_path,
                    start_position=-len(full_match),
                    display=file_path,
                )


COMPLETION_STYLE = Style.from_dict(
    {
        "bottom-toolbar": "noinherit",
        "completion-menu.completion": "noinherit",
        "completion-menu.completion.current": (
            f"noinherit fg:{PROMPT_TOOLKIT_ACCENT_COLOR} bold"
        ),
        "completion-menu.meta.completion": "noinherit",
        "completion-menu.meta.completion.current": (
            f"noinherit fg:{PROMPT_TOOLKIT_ACCENT_COLOR} bold"
        ),
        "scrollbar.background": "noinherit",
        "scrollbar.button": "noinherit",
        "scrollbar.arrow-up": "noinherit",
        "scrollbar.arrow-down": "noinherit",
    }
)
