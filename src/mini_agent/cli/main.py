import argparse
import uuid
from html import escape

from anthropic.types import MessageParam
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.shortcuts import print_formatted_text

from ..agent.agent import agent_loop
from ..config import config
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
)
from .token import token_tracker


def build_session() -> PromptSession:
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

    return PromptSession(
        HTML(f'<style color="{PROMPT_ACCENT_COLOR}">> </style>'),
        multiline=True,
        key_bindings=bindings,
        completer=CommandCompleter(),
        complete_while_typing=True,
        style=COMPLETION_STYLE,
        bottom_toolbar=get_status_toolbar,
    )


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
    session = build_session()

    if prompt is not None:
        print_formatted_text(
            HTML(f'<style color="{PROMPT_ACCENT_COLOR}">&gt; </style>{escape(prompt)}')
        )
        print()
        history.append({"role": "user", "content": prompt})
        history_len = len(history)
        agent_loop(history)
        if len(history) > history_len:
            save_session_history(current_session_id, history, token_tracker.get())

    if session_id is not None:
        current_session_id = session_id
        sessions = list_sessions()
        chosen = next(stored for stored in sessions if stored.session_id == session_id)
        clear_terminal()
        print_session_history(chosen.history)
        if chosen.last_usage is not None:
            token_tracker.restore(chosen.last_usage)

    while True:
        try:
            query = session.prompt()
            print()
        except KeyboardInterrupt:
            continue
        except EOFError:
            break

        command = query.strip().lower()
        if command in {"", "q", "exit"}:
            break
        if command == "/new":
            history.clear()
            current_session_id = uuid.uuid4().hex
            token_tracker.reset()
            clear_terminal()
            continue
        if command == "/resume":
            current_session_id, history = prompt_resume(current_session_id, history)
            continue
        if command == "/model":
            prompt_model()
            continue

        history.append({"role": "user", "content": query})
        history_len = len(history)
        agent_loop(history)

        if len(history) <= history_len:
            continue

        save_session_history(current_session_id, history, token_tracker.get())


def main() -> None:
    parser = argparse.ArgumentParser(description="A minimal agent.")
    parser.add_argument(
        "-m",
        "--model",
        type=str,
        help="Model for the current session",
    )
    parser.add_argument(
        "-p",
        "--prompt",
        dest="non_interactive_prompt",
        type=str,
        help="Run a single prompt non-interactively and exit",
    )
    parser.add_argument(
        "-r",
        "--resume",
        dest="session_id",
        type=str,
        help="Resume a specific session by ID ",
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

    if args.non_interactive_prompt:
        _run_non_interactive(args.non_interactive_prompt)
        return

    _run_interactive(args.prompt, args.session_id)
