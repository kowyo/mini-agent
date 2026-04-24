import re
from collections.abc import Callable

from anthropic.types import ImageBlockParam
from prompt_toolkit import PromptSession
from prompt_toolkit.application import get_app
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent

from .clipboard import format_image_indicator, get_clipboard_image
from .display import COMPLETION_STYLE, CommandCompleter
from .display.theme import PROMPT_TOOLKIT_ACCENT_COLOR
from .display.toolbar import get_status_toolbar


def _sync_attached_images_with_buffer(
    buffer_text: str,
    attached_images: list[tuple[int, ImageBlockParam]],
) -> None:
    if not attached_images:
        return

    attached_images[:] = [
        (num, image_block)
        for num, image_block in attached_images
        if format_image_indicator(num) in buffer_text
    ]


def build_session(
    prompt: str | None = None,
) -> tuple[
    PromptSession,
    Callable[[], None] | None,
    list[tuple[int, ImageBlockParam]],
    list[int],
    list[int],
]:
    bindings = KeyBindings()
    attached_images: list[tuple[int, ImageBlockParam]] = []
    sent_image_count = [0]
    next_indicator = [1]

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
        indicator_match = re.search(r"\[Image #\d+\]$", text_before_cursor)

        if indicator_match is not None:
            buffer.delete_before_cursor(count=len(indicator_match.group(0)))
        else:
            buffer.delete_before_cursor(count=1)

        _sync_attached_images_with_buffer(
            event.current_buffer.text,
            attached_images,
        )

    @bindings.add("c-v")
    def paste_clipboard_image(event: KeyPressEvent) -> None:
        """Paste image from clipboard with Ctrl+V."""
        image = get_clipboard_image()
        if image is None:
            return

        from .clipboard import create_image_content

        image_block = create_image_content(image)
        indicator_num = next_indicator[0]
        next_indicator[0] += 1
        attached_images.append((indicator_num, image_block))

        current_text = event.current_buffer.text
        indicator = format_image_indicator(indicator_num)
        if indicator not in current_text:
            event.current_buffer.insert_text(indicator)

    session = PromptSession(
        HTML(f'<style color="{PROMPT_TOOLKIT_ACCENT_COLOR}">> </style>'),
        multiline=True,
        key_bindings=bindings,
        completer=CommandCompleter(),
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

    return session, pre_run, attached_images, sent_image_count, next_indicator
