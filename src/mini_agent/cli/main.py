import argparse
import uuid
from collections.abc import Callable
from importlib.metadata import version
from typing import Any

from anthropic.types import MessageParam
from prompt_toolkit import PromptSession
from prompt_toolkit.application import get_app
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from rich.console import Console

from ..agent.agent import agent_loop
from ..config import REASONING_EFFORT_LEVELS, config
from .clipboard import create_image_content_block, get_clipboard_image
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

console = Console()


def build_session(
    prompt: str | None = None,
    attached_images: list[dict] | None = None,
) -> tuple[PromptSession, Callable[[], None] | None]:
    bindings = KeyBindings()

    @bindings.add("c-c")
    def clear_buffer(event: KeyPressEvent) -> None:
        event.current_buffer.reset()

    @bindings.add("enter")
    def submit(event: KeyPressEvent) -> None:
        event.current_buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    def insert_newline(event: KeyPressEvent) -> None:
        event.current_buffer.insert_text("\n")

    @bindings.add("c-v")
    def paste_image(event: KeyPressEvent) -> None:
        """Paste image from clipboard."""
        img = get_clipboard_image()
        if img is not None:
            if attached_images is not None:
                attached_images.append(create_image_content_block(img))
                # Show feedback that image was attached
                console.print(
                    f"[dim]📎 Image attached ({img.width}x{img.height})[/dim]"
                )
        else:
            # No image in clipboard, try normal paste behavior
            # by letting the default handler process it
            event.app.clipboard.get_data()

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

    return session, pre_run


def create_user_message(query: str, images: list[dict]) -> MessageParam:
    """Create a user message with optional image content."""
    if images:
        # Multimodal message with text and images
        content: list[dict[str, Any]] = []
        if query.strip():
            content.append({"type": "text", "text": query})
        content.extend(images)
        return {"role": "user", "content": content}
    # Text-only message
    return {"role": "user", "content": query}


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
    # Track images attached via Ctrl+V for the next message
    attached_images: list[dict] = []
    session, pre_run = build_session(prompt, attached_images)

    if session_id is not None:
        current_session_id = session_id
        sessions = list_sessions()
        try:
            chosen = next(
                stored for stored in sessions if stored.session_id == current_session_id
            )
            history = chosen.history.copy()
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
            continue
        except EOFError:
            break

        command = query.strip().lower()
        if command in {"", "q", "/exit"}:
            break
        if command == "/new":
            history.clear()
            current_session_id = uuid.uuid4().hex
            token_tracker.reset()
            attached_images.clear()
            clear_terminal()
            print_welcome_banner()
            continue
        if command == "/resume":
            current_session_id, history, _ = prompt_resume(current_session_id, history)
            attached_images.clear()
            continue
        if command == "/model":
            prompt_model()
            continue

        # Create message with attached images and add to history
        message = create_user_message(query, attached_images)
        history.append(message)
        # Clear attached images after sending
        attached_images.clear()

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
