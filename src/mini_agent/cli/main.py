import argparse
import sys

from rich.console import Console
lazy from anthropic.types import MessageParam

from ..config import (
    DISTRIBUTION_NAME,
    DISTRIBUTION_VERSION,
    REASONING_EFFORT_LEVELS,
    config,
)
from .banner import print_welcome_banner
from .clipboard import copy_last_assistant_text
from .display.box import print_box
from .display.theme import ACCENT_COLOR
from .prompt_session import build_session
from .providers import prompt_provider
from .sessions import SessionManager, prompt_resume
from .terminal import clear_prompt_line, clear_terminal
from .token import token_tracker
lazy from ..agent.agent import agent_loop
lazy from ..agent.mcp import setup_mcp, shutdown_mcp
lazy from .display.printing import print_session_history
lazy from .image_messages import build_user_content, count_images_in_history
lazy from .mcp import McpSetup, print_mcp_hint, print_mcp_lines, prompt_mcp
lazy from .models import prompt_model
lazy from .status import format_status_report, format_usage_report
lazy from .update import run_update

_console = Console()

_session_manager = SessionManager()


def _run_non_interactive(prompt: str) -> None:
    print_mcp_lines(setup_mcp())
    history: list[MessageParam] = [{"role": "user", "content": prompt}]
    session_id = _session_manager.new_id()
    history_len = len(history)
    agent_loop(history)
    if len(history) > history_len and token_tracker.get() is not None:
        _session_manager.save(session_id, history, token_tracker.round_usages)


def _run_interactive(prompt: str | None = None, session_id: str | None = None) -> None:
    print_welcome_banner()

    history: list[MessageParam] = []
    current_session_id = _session_manager.new_id()
    session, pre_run, attached_images, sent_image_count = build_session(
        lambda: history, prompt
    )
    mcp_setup = McpSetup()

    if session_id is not None:
        current_session_id = session_id
        sessions = _session_manager.list_sessions()
        try:
            chosen = next(
                stored for stored in sessions if stored.session_id == current_session_id
            )
            history = chosen.history.copy()
            sent_image_count[0] = count_images_in_history(history)
            print_session_history(chosen.history)
            token_tracker.restore(chosen.round_usages)
        except StopIteration:
            print("Session ID not found.\n")

    while True:
        try:
            query = session.prompt(pre_run=pre_run)
            pre_run = None
        except KeyboardInterrupt:
            clear_prompt_line()
            attached_images.clear()
            continue
        except EOFError:
            clear_prompt_line()
            break

        command = query.strip().lower()
        if command in {"", "q", "/exit"}:
            clear_prompt_line()
            break

        print()
        if command == "/new":
            history.clear()
            current_session_id = _session_manager.new_id()
            sent_image_count[0] = 0
            token_tracker.reset()
            attached_images.clear()
            clear_terminal()
            print_welcome_banner()
            print_mcp_hint()
            continue
        if command == "/resume":
            current_session_id, history, _ = prompt_resume(
                _session_manager, current_session_id, history
            )
            sent_image_count[0] = count_images_in_history(history)
            attached_images.clear()
            continue
        if command == "/model":
            prompt_model()
            attached_images.clear()
            continue
        if command == "/provider":
            prompt_provider()
            attached_images.clear()
            continue
        if command == "/status":
            mcp_setup.wait()
            print_box(_console, format_status_report(current_session_id))
            print()
            attached_images.clear()
            continue
        if command == "/copy":
            copy_last_assistant_text(history)
            print()
            attached_images.clear()
            continue
        if command == "/mcp":
            mcp_setup.wait()
            prompt_mcp()
            attached_images.clear()
            continue

        mcp_setup.wait()
        content = build_user_content(query, attached_images, sent_image_count)

        history.append({"role": "user", "content": content})
        history_len = len(history)
        agent_loop(history)

        if len(history) <= history_len:
            continue
        if token_tracker.get() is not None:
            _session_manager.save(
                current_session_id, history, token_tracker.round_usages
            )

    if _session_manager.exists(current_session_id):
        usage_report = format_usage_report(token_tracker.get())
        if usage_report:
            for line in usage_report:
                _console.print(line)
            print()
        print("Resume the session with:")
        _console.print(f"mini --resume {current_session_id}", style=ACCENT_COLOR)
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "A minimal agent.\n\n"
            "commands:\n"
            "  update                Update to the latest release"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"{DISTRIBUTION_NAME} {DISTRIBUTION_VERSION}",
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
        "--provider",
        type=str,
        help="Provider ID from config.toml for the current session",
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

    if args.prompt == "update":
        sys.exit(run_update())

    if args.model:
        config.set_session_model(args.model)

    if args.effort:
        config.set_session_reasoning_effort(args.effort)

    if args.provider:
        config.set_session_provider(args.provider)

    try:
        config.get_provider()
    except ValueError as e:
        parser.exit(1, f"{e}\n")

    session_id: str | None = args.session_id
    if session_id == "__LATEST__":
        sessions = _session_manager.list_sessions()
        if not sessions:
            print("No saved sessions found.")
            return
        session_id = sessions[0].session_id

    try:
        if args.print_prompt:
            _run_non_interactive(args.print_prompt)
        else:
            _run_interactive(args.prompt, session_id)
    finally:
        shutdown_mcp()
