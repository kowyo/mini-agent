import argparse
import sys
import threading
from typing import TYPE_CHECKING

from rich.console import Console

from ..config import (
    DISTRIBUTION_NAME,
    DISTRIBUTION_VERSION,
    REASONING_EFFORT_LEVELS,
    config,
)
from .banner import print_welcome_banner
from .display.theme import LIGHT_HINT_STYLE_RICH

if TYPE_CHECKING:
    from anthropic.types import MessageParam

    from .sessions import SessionManager

_console = Console()

_session_manager: SessionManager | None = None
_mcp_setup_done = threading.Event()
_mcp_setup_lines: list[str] = []
_mcp_setup_error: BaseException | None = None
_mcp_setup_reported = False
_mcp_started = False


def _get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        from .sessions import SessionManager

        _session_manager = SessionManager()
    return _session_manager


def _setup_mcp() -> None:
    global _mcp_started
    from ..agent.mcp import setup_mcp

    _mcp_started = True
    try:
        mcp_lines = setup_mcp()
    finally:
        _mcp_setup_done.set()
    if mcp_lines:
        for line in mcp_lines:
            _console.print(line, style=LIGHT_HINT_STYLE_RICH)
        print()


def _start_mcp_setup() -> None:
    global _mcp_started
    _mcp_started = True

    def run() -> None:
        global _mcp_setup_lines, _mcp_setup_error
        try:
            from ..agent.mcp import setup_mcp

            _mcp_setup_lines = setup_mcp()
        except BaseException as exc:
            _mcp_setup_error = exc
        finally:
            _mcp_setup_done.set()

    threading.Thread(target=run, name="mcp-setup", daemon=True).start()


def _flush_mcp_setup(block: bool) -> bool:
    global _mcp_setup_error, _mcp_setup_reported
    if _mcp_setup_reported:
        return False
    if not _mcp_setup_done.is_set():
        if not block:
            return False
        _mcp_setup_done.wait()
    _mcp_setup_reported = True
    if _mcp_setup_lines:
        for line in _mcp_setup_lines:
            _console.print(line, style=LIGHT_HINT_STYLE_RICH)
        print()
    if _mcp_setup_error is not None:
        error = _mcp_setup_error
        _mcp_setup_error = None
        raise error
    from .mcp import print_mcp_hint

    print_mcp_hint()
    return True


def _run_non_interactive(prompt: str) -> None:
    from ..agent.agent import agent_loop
    from .token import token_tracker

    history: list[MessageParam] = [{"role": "user", "content": prompt}]
    session_manager = _get_session_manager()
    session_id = session_manager.new_id()
    history_len = len(history)
    agent_loop(history)
    if len(history) > history_len and token_tracker.get() is not None:
        session_manager.save(session_id, history, token_tracker.round_usages)


def _run_interactive(prompt: str | None = None, session_id: str | None = None) -> None:
    print_welcome_banner()
    _start_mcp_setup()

    from ..agent.agent import agent_loop
    from .clipboard import copy_last_assistant_text
    from .display.box import print_box
    from .display.printing import (
        clear_prompt_line,
        clear_terminal,
        print_session_history,
    )
    from .display.theme import ACCENT_COLOR
    from .image_messages import (
        build_user_content,
        count_images_in_history,
    )
    from .mcp import print_mcp_hint, prompt_mcp
    from .models import prompt_model
    from .prompt_session import build_session
    from .providers import prompt_provider
    from .sessions import prompt_resume
    from .status import (
        format_status_report,
        format_usage_report,
    )
    from .token import token_tracker

    history: list[MessageParam] = []
    session_manager = _get_session_manager()
    current_session_id = session_manager.new_id()
    session, pre_run, attached_images, sent_image_count = build_session(
        lambda: history, prompt
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
            print_session_history(chosen.history)
            token_tracker.restore(chosen.round_usages)
        except StopIteration:
            print("Session ID not found.\n")

    _flush_mcp_setup(block=False)

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
            sent_image_count[0] = 0
            token_tracker.reset()
            attached_images.clear()
            clear_terminal()
            print_welcome_banner()
            if not _flush_mcp_setup(block=False):
                print_mcp_hint()
            continue
        if command == "/resume":
            current_session_id, history, _ = prompt_resume(
                session_manager, current_session_id, history
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
            _flush_mcp_setup(block=True)
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
            _flush_mcp_setup(block=True)
            prompt_mcp()
            attached_images.clear()
            continue

        _flush_mcp_setup(block=True)
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

    if session_manager.exists(current_session_id):
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
        from .update import run_update

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

    try:
        if args.print_prompt:
            _setup_mcp()
            _run_non_interactive(args.print_prompt)
            return

        session_id: str | None = args.session_id
        if session_id == "__LATEST__":
            sessions = _get_session_manager().list_sessions()
            if sessions:
                session_id = sessions[0].session_id
            else:
                print("No saved sessions found.")
                return

        _run_interactive(args.prompt, session_id)
    finally:
        if _mcp_started and _mcp_setup_done.is_set():
            from ..agent.mcp import shutdown_mcp

            shutdown_mcp()
