from collections.abc import Callable, Iterable
from typing import cast

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.data_structures import Point
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text.base import StyleAndTextTuples
from prompt_toolkit.layout import controls as pt_controls
from prompt_toolkit.layout import menus as pt_menus
from prompt_toolkit.styles import Style

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
