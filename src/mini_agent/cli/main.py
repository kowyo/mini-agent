import argparse
import re
import uuid
from collections.abc import Callable
from importlib.metadata import version

from anthropic.types import ImageBlockParam, MessageParam, TextBlockParam
from prompt_toolkit import PromptSession
from prompt_toolkit.application import get_app
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent

from ..agent.agent import agent_loop
from ..config import REASONING_EFFORT_LEVELS, config
from .clipboard import format_image_indicator, get_clipboard_image
from .display import (
    COMPLETION_STYLE,
    CommandCompleter,
    clear_terminal,
    print_welcome_banner,
)
from .display.theme import PROMPT_ACCENT_COLOR
from .display.toolbar import get_status_toolbar
from .models import prompt_model
from .sessions import (
    list_sessions,
    print_session_history,
    prompt_resume,
    save_session_history,
    session_saved,
)
from .token import token_tracker


def build_session(
    prompt: str | None = None,
) -> tuple[PromptSession, Callable[[], None] | None, list[ImageBlockParam], list[int]]:
    bindings = KeyBindings()
    attached_images: list[ImageBlockParam] = []
    sent_image_count = [0]

    def sync_attached_images_with_buffer(buffer_text: str) -> None:
        if not attached_images:
            return

        kept_images: list[ImageBlockParam] = []
        for i, image_block in enumerate(attached_images, start=1):
            indicator = format_image_indicator(sent_image_count[0] + i)
            if indicator in buffer_text:
                kept_images.append(image_block)

        attached_images[:] = kept_images

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

        sync_attached_images_with_buffer(event.current_buffer.text)

    @bindings.add("c-v")
    def paste_clipboard_image(event: KeyPressEvent) -> None:
        """Paste image from clipboard with Ctrl+V."""
        image = get_clipboard_image()
        if image is None:
            # No image in clipboard, let the default paste handler work
            return

        from .clipboard import create_image_content

        image_block = create_image_content(image)
        attached_images.append(image_block)

        # Show visual feedback in the buffer
        current_text = event.current_buffer.text
        indicator = format_image_indicator(sent_image_count[0] + len(attached_images))
        if indicator not in current_text:
            event.current_buffer.insert_text(indicator)

    session = PromptSession(
        HTML(f'<style color="{PROMPT_ACCENT_COLOR}">> </style>'),
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

    return session, pre_run, attached_images, sent_image_count


def _count_images_in_history(history: list[MessageParam]) -> int:
    image_count = 0
    for message in history:
        if message["role"] != "user" or not isinstance(message["content"], list):
            continue
        for block in message["content"]:
            if isinstance(block, dict) and block.get("type") == "image":
                image_count += 1
    return image_count


def _run_non_interactive(prompt: str) -> None:
    """Run the agent on a single prompt and exit (non-interactive mode)."""
    history: list[MessageParam] = [{"role": "user", "content": prompt}]
    current_session_id = uuid.uuid4().hex
    history_len = len(history)
    agent_loop(history)
    if len(history) > history_len:
        save_session_history(current_session_id, history, token_tracker.get())


def _run_interactive(prompt: str | None = None, session_id: str | None = None) -> None:
    """Run the interactive TUI session."""
    print_welcome_banner()
    history: list[MessageParam] = []
    current_session_id = uuid.uuid4().hex
    session, pre_run, attached_images, sent_image_count = build_session(prompt)

    if session_id is not None:
        current_session_id = session_id
        sessions = list_sessions()
        try:
            chosen = next(
                stored for stored in sessions if stored.session_id == current_session_id
            )
            history = chosen.history.copy()
            sent_image_count[0] = _count_images_in_history(history)
            print_session_history(chosen.history)
            if chosen.last_usage is not None:
                token_tracker.restore(chosen.last_usage)
        except StopIteration:
            print("Session ID not found.\n")

    while True:
        try:
            query = session.prompt(pre_run=pre_run)
            pre_run = None
            print()
        except KeyboardInterrupt:
            attached_images.clear()
            continue
        except EOFError:
            break

        command = query.strip().lower()
        if command in {"", "q", "/exit"}:
            break
        if command == "/new":
            history.clear()
            current_session_id = uuid.uuid4().hex
            sent_image_count[0] = 0
            token_tracker.reset()
            attached_images.clear()
            clear_terminal()
            print_welcome_banner()
            continue
        if command == "/resume":
            current_session_id, history, _ = prompt_resume(current_session_id, history)
            sent_image_count[0] = _count_images_in_history(history)
            attached_images.clear()
            continue
        if command == "/model":
            prompt_model()
            attached_images.clear()
            continue

        # Build content with attached images
        content: str | list[ImageBlockParam | TextBlockParam]
        if attached_images:
            # If indicator text was edited away, don't send orphaned images.
            attached_images[:] = [
                image_block
                for i, image_block in enumerate(attached_images, start=1)
                if format_image_indicator(sent_image_count[0] + i) in query
            ]

        if attached_images:
            content = []
            # Add all attached images
            content.extend(attached_images)
            # Add text content if not empty
            if query.strip():
                text_block: TextBlockParam = {"type": "text", "text": query}
                content.append(text_block)
            sent_image_count[0] += len(attached_images)
            attached_images.clear()
        else:
            content = query

        history.append({"role": "user", "content": content})
        history_len = len(history)
        agent_loop(history)

        if len(history) <= history_len:
            continue

        save_session_history(current_session_id, history, token_tracker.get())

    if session_saved(current_session_id):
        print(f"\nResume the session with:\nmini-agent --resume {current_session_id}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="A minimal agent.")
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {version('mini-agent')}",
    )
    parser.add_argument(
        "-m",
        "--model",
        type=str,
        help="Model for the current session",
    )
    parser.add_argument(
        "-e",
        "--effort",
        type=str,
        choices=REASONING_EFFORT_LEVELS,
        help="Set the effort level for the current session",
    )
    parser.add_argument(
        "-p",
        "--print",
        dest="print_prompt",
        type=str,
        help="Print response without interactive mode",
    )
    parser.add_argument(
        "-r",
        "--resume",
        dest="session_id",
        nargs="?",
        const="__LATEST__",
        type=str,
        help="Resume a session by ID, or resume the most recent session if no ID provided",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        type=str,
        help="Start interactive session with initial prompt",
    )
    args = parser.parse_args()

    if args.model:
        config.set_session_model(args.model)

    if args.effort:
        config.set_session_reasoning_effort(args.effort)

    if args.print_prompt:
        _run_non_interactive(args.print_prompt)
        return

    session_id: str | None = args.session_id
    if session_id == "__LATEST__":
        sessions = list_sessions()
        if sessions:
            session_id = sessions[0].session_id
        else:
            print("No saved sessions found.")
            return

    _run_interactive(args.prompt, session_id)
