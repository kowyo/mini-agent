import argparse

from anthropic.types import MessageParam
from rich.console import Console

from ..agent.agent import agent_loop
from ..config import (
    DISTRIBUTION_NAME,
    DISTRIBUTION_VERSION,
    REASONING_EFFORT_LEVELS,
    config,
)
from ..plugin import PluginManager
from .clipboard import copy_last_assistant_text
from .display import (
    ACCENT_COLOR,
    clear_prompt_line,
    clear_terminal,
    print_box,
    print_welcome_banner,
)
from .image_messages import (
    build_user_content,
    count_images_in_history,
    max_indicator_in_history,
)
from .models import prompt_model
from .prompt_session import build_session
from .sessions import (
    SessionManager,
    print_session_history,
    prompt_resume,
)
from .status import (
    format_status_report,
    format_usage_report,
)
from .token import token_tracker

console = Console()

session_manager = SessionManager()
plugin_manager = PluginManager.discover()


def _run_non_interactive(prompt: str) -> None:
    history: list[MessageParam] = [{"role": "user", "content": prompt}]
    session_id = session_manager.new_id()
    plugin_manager.on_session_start(session_id)
    history_len = len(history)
    agent_loop(history)
    if len(history) > history_len and token_tracker.get() is not None:
        session_manager.save(session_id, history, token_tracker.round_usages)
        plugin_manager.on_turn_complete(session_id, history, token_tracker.round_usages)


def _run_interactive(
    prompt: str | None = None,
    session_id: str | None = None,
) -> None:
    print_welcome_banner()
    history: list[MessageParam] = []
    current_session_id = session_manager.new_id()
    session, pre_run, attached_images, sent_image_count, next_indicator = build_session(
        prompt
    )

    if session_id is not None:
        current_session_id = session_id
        sessions = session_manager.list_sessions()
        try:
            chosen = next(
                stored for stored in sessions if stored.session_id == current_session_id
            )
            history = chosen.history.copy()
            sent_image_count[0] = count_images_in_history(history)
            next_indicator[0] = max_indicator_in_history(history) + 1
            print_session_history(chosen.history)
            token_tracker.restore(chosen.round_usages)
        except StopIteration:
            print("Session ID not found.\n")

    plugin_manager.on_session_start(current_session_id)

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
            current_session_id = session_manager.new_id()
            plugin_manager.on_session_start(current_session_id)
            sent_image_count[0] = 0
            next_indicator[0] = 1
            token_tracker.reset()
            attached_images.clear()
            clear_terminal()
            print_welcome_banner()
            continue
        if command == "/resume":
            current_session_id, history, _ = prompt_resume(
                session_manager, current_session_id, history
            )
            plugin_manager.on_session_start(current_session_id)
            sent_image_count[0] = count_images_in_history(history)
            next_indicator[0] = max_indicator_in_history(history) + 1
            attached_images.clear()
            continue
        if command == "/model":
            prompt_model()
            attached_images.clear()
            continue
        if command == "/status":
            print_box(console, format_status_report(current_session_id))
            print()
            attached_images.clear()
            continue
        if command == "/copy":
            copy_last_assistant_text(history)
            print()
            attached_images.clear()
            continue
        if command == "/plugins":
            plugins = plugin_manager.list_plugins()
            if plugins:
                print(f"Active plugins: {', '.join(plugins)}")
            else:
                print("No plugins loaded.")
            print()
            attached_images.clear()
            continue

        content = build_user_content(query, attached_images, sent_image_count)

        history.append({"role": "user", "content": content})
        history_len = len(history)
        agent_loop(history)

        if len(history) <= history_len:
            continue
        if token_tracker.get() is not None:
            session_manager.save(
                current_session_id, history, token_tracker.round_usages
            )
            plugin_manager.on_turn_complete(
                current_session_id, history, token_tracker.round_usages
            )

    plugin_manager.on_session_end(
        current_session_id, history, token_tracker.round_usages
    )

    if session_manager.exists(current_session_id):
        usage_report = format_usage_report(token_tracker.get())
        if usage_report:
            for line in usage_report:
                console.print(line)
            print()
        print("Resume the session with:")
        console.print(f"mini --resume {current_session_id}", style=ACCENT_COLOR)
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="A minimal agent.")
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

    plugin_manager.on_agent_init()

    if args.model:
        config.set_session_model(args.model)

    if args.effort:
        config.set_session_reasoning_effort(args.effort)

    if args.print_prompt:
        _run_non_interactive(args.print_prompt)
        return

    session_id: str | None = args.session_id
    if session_id == "__LATEST__":
        sessions = session_manager.list_sessions()
        if sessions:
            session_id = sessions[0].session_id
        else:
            print("No saved sessions found.")
            return

    _run_interactive(args.prompt, session_id)
