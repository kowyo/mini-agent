import argparse
import uuid
from collections.abc import Callable
from importlib.metadata import version

from anthropic.types import MessageParam
from prompt_toolkit import PromptSession
from prompt_toolkit.application import get_app
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent

from ..agent.agent import agent_loop
from ..config import REASONING_EFFORT_LEVELS, config
from .clipboard import get_clipboard_image
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
) -> tuple[PromptSession, Callable[[], None] | None, list[dict]]:
    bindings = KeyBindings()
    attached_images: list[dict] = []

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
        indicator = "[Image attached]"
        if indicator not in current_text:
            if current_text and not current_text.endswith("\n"):
                event.current_buffer.insert_text("\n")
            event.current_buffer.insert_text(f"{indicator}\n")

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

    return session, pre_run, attached_images


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
    session, pre_run, attached_images = build_session(prompt)

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
            attached_images.clear()
            continue

        # Build content with attached images
        content: str | list[dict]
        if attached_images:
            # Remove the indicator text from query
            clean_query = query.replace("[Image attached]", "").strip()
            content = []
            # Add all attached images
            content.extend(attached_images)
            # Add text content if not empty
            if clean_query:
                content.append({"type": "text", "text": clean_query})
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
