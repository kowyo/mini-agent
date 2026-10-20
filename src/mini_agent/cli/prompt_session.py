from collections.abc import Callable

from prompt_toolkit import PromptSession
from prompt_toolkit.application import get_app, run_in_terminal
from prompt_toolkit.completion import merge_completers
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
lazy from anthropic.types import ImageBlockParam, MessageParam

from .clipboard import (
    create_image_content,
    format_image_indicator,
    get_clipboard_image,
)
from .display.completion import COMPLETION_STYLE, CommandCompleter, FileCompleter
from .display.theme import PROMPT_TOOLKIT_ACCENT_COLOR
from .display.toolbar import get_status_toolbar
lazy from .display.printing import print_session_history, toggle_full_tool_output


def _sync_attached_images_with_buffer(
    buffer_text: str,
    attached_images: list[tuple[str, ImageBlockParam]],
) -> None:
    if not attached_images:
        return

    attached_images[:] = [
        (path, image_block)
        for path, image_block in attached_images
        if format_image_indicator(path) in buffer_text
    ]


def build_session(
    get_history: Callable[[], list[MessageParam]],
    prompt: str | None = None,
) -> tuple[
    PromptSession,
    Callable[[], None] | None,
    list[tuple[str, ImageBlockParam]],
    list[int],
]:
    bindings = KeyBindings()
    attached_images: list[tuple[str, ImageBlockParam]] = []
    sent_image_count = [0]

    @bindings.add("c-c")
    def clear_buffer(event: KeyPressEvent) -> None:
        event.current_buffer.reset()
        attached_images.clear()

    @bindings.add("enter")
    def submit(event: KeyPressEvent) -> None:
        event.current_buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    def insert_newline(event: KeyPressEvent) -> None:
        event.current_buffer.insert_text("\n")

    @bindings.add("backspace")
    def delete_backwards(event: KeyPressEvent) -> None:
        buffer = event.current_buffer
        text_before_cursor = buffer.document.text_before_cursor
        indicator_match = next(
            (
                (path, image_block)
                for path, image_block in attached_images
                if text_before_cursor.endswith(path)
            ),
            None,
        )

        if indicator_match is not None:
            buffer.delete_before_cursor(count=len(indicator_match[0]))
        else:
            buffer.delete_before_cursor(count=1)

        _sync_attached_images_with_buffer(
            event.current_buffer.text,
            attached_images,
        )

    @bindings.add("c-o")
    def toggle_tool_output(event: KeyPressEvent) -> None:
        toggle_full_tool_output()
        run_in_terminal(lambda: print_session_history(get_history()))

    @bindings.add("c-v")
    def paste_clipboard_image(event: KeyPressEvent) -> None:
        """Paste image from clipboard with Ctrl+V."""
        result = get_clipboard_image()
        if result is None:
            return

        image, image_path = result
        image_block = create_image_content(image)

        current_text = event.current_buffer.text
        indicator = format_image_indicator(image_path)
        if indicator in current_text:
            return
        attached_images.append((image_path, image_block))
        event.current_buffer.insert_text(indicator)

    session = PromptSession(
        HTML(f'<style color="{PROMPT_TOOLKIT_ACCENT_COLOR}">> </style>'),
        multiline=True,
        key_bindings=bindings,
        completer=merge_completers(
            [
                CommandCompleter(),
                FileCompleter(),
            ]
        ),
        complete_while_typing=True,
        style=COMPLETION_STYLE,
        bottom_toolbar=get_status_toolbar,
    )

    pre_run: Callable[[], None] | None = None
    if prompt:

        def pre_run() -> None:
            app = get_app()
            app.current_buffer.set_document(Document(prompt), bypass_readonly=True)
            app.current_buffer.validate_and_handle()

    return session, pre_run, attached_images, sent_image_count
