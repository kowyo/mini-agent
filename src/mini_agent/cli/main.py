import sys
import uuid
from collections.abc import Callable
from typing import Annotated

import click
from anthropic.types import MessageParam
from prompt_toolkit import PromptSession
from prompt_toolkit.application import get_app
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from typer import Argument, Exit, Option, Typer

from ..agent.agent import agent_loop
from ..config import CLI_NAME, CLI_VERSION, REASONING_EFFORT_LEVELS, config
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


def _fix_resume_args() -> None:
    """Fix -r/--resume args to support optional value (nargs='?' behavior)."""
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg in ("-r", "--resume") and (
            i + 1 >= len(args) or args[i + 1].startswith("-")
        ):
            # Insert __LATEST__ after -r/--resume when no value provided
            sys.argv.insert(i + 2, "__LATEST__")
            break


# Apply fix before Typer parses arguments
_fix_resume_args()

app = Typer(
    help="A minimal agent.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


def build_session(
    prompt: str | None = None,
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
    session, pre_run = build_session(prompt)

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
            clear_terminal()
            print_welcome_banner()
            continue
        if command == "/resume":
            current_session_id, history, _ = prompt_resume(current_session_id, history)
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

    if session_saved(current_session_id):
        print(f"\nResume the session with:\nmini-agent --resume {current_session_id}\n")


def version_callback(value: bool) -> None:
    if value:
        print(f"{CLI_NAME} {CLI_VERSION}")
        raise Exit(0)


@app.callback(invoke_without_command=True)
def main(
    prompt: Annotated[
        str | None, Argument(help="Start interactive session with initial prompt")
    ] = None,
    version: Annotated[
        bool,
        Option(
            "-v",
            "--version",
            help="Show version",
            callback=version_callback,
            is_eager=True,
        ),
    ] = False,
    model: Annotated[
        str | None, Option("-m", "--model", help="Model for the current session")
    ] = None,
    effort: Annotated[
        str | None,
        Option(
            "-e",
            "--effort",
            help="Set the effort level for the current session",
            click_type=click.Choice(REASONING_EFFORT_LEVELS),
        ),
    ] = None,
    print_prompt: Annotated[
        str | None,
        Option("-p", "--print", help="Print response without interactive mode"),
    ] = None,
    resume: Annotated[
        str | None,
        Option(
            "-r",
            "--resume",
            help="Resume a session by ID, or resume the most recent session if no ID provided",
        ),
    ] = None,
) -> None:
    """A minimal agent."""
    if model:
        config.set_session_model(model)

    if effort:
        config.set_session_reasoning_effort(effort)

    if print_prompt:
        _run_non_interactive(print_prompt)
        return

    session_id = resume
    if session_id == "__LATEST__":
        sessions = list_sessions()
        if sessions:
            session_id = sessions[0].session_id
        else:
            print("No saved sessions found.")
            raise Exit(1)

    _run_interactive(prompt, session_id)
