import argparse
import uuid
from importlib.metadata import version

from anthropic.types import MessageParam

from ..agent.agent import agent_loop
from ..config import REASONING_EFFORT_LEVELS, config
from .display import (
    clear_terminal,
    print_welcome_banner,
)
from .image_messages import build_user_content, count_images_in_history
from .models import prompt_model
from .prompt_session import build_session
from .sessions import (
    list_sessions,
    print_session_history,
    prompt_resume,
    save_session_history,
    session_saved,
)
from .token import token_tracker


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
    session, pre_run, attached_images, sent_image_count, next_indicator = build_session(
        prompt
    )

    if session_id is not None:
        current_session_id = session_id
        sessions = list_sessions()
        try:
            chosen = next(
                stored for stored in sessions if stored.session_id == current_session_id
            )
            history = chosen.history.copy()
            sent_image_count[0] = count_images_in_history(history)
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
            next_indicator[0] = 1
            token_tracker.reset()
            attached_images.clear()
            clear_terminal()
            print_welcome_banner()
            continue
        if command == "/resume":
            current_session_id, history, _ = prompt_resume(current_session_id, history)
            sent_image_count[0] = count_images_in_history(history)
            next_indicator[0] = sent_image_count[0] + 1
            attached_images.clear()
            continue
        if command == "/model":
            prompt_model()
            attached_images.clear()
            continue

        content = build_user_content(query, attached_images, sent_image_count)

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
