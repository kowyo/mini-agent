import argparse
import sys

from rich.console import Console

from ..agent.agent import agent_loop
from ..agent.mcp import setup_mcp, shutdown_mcp
from ..agent.system_prompt import SYSTEM
from ..agent.tools import TOOLS
from ..agent.transcript import Message, Transcript, UserMessage
from ..chatgpt import ChatGPTAuthError, is_logged_in, login, logout
from ..config import (
    DISTRIBUTION_NAME,
    DISTRIBUTION_VERSION,
    REASONING_EFFORT_LEVELS,
    config,
)
from .clipboard import copy_last_assistant_text
from .display import (
    ACCENT_COLOR,
    clear_prompt_line,
    clear_terminal,
    print_box,
    print_welcome_banner,
)
from .display.theme import LIGHT_HINT_STYLE_RICH
from .image_messages import (
    build_user_content,
    count_images_in_history,
)
from .mcp import print_mcp_hint, prompt_mcp
from .models import _fetch_models, prompt_model
from .prompt_session import build_session
from .providers import prompt_provider
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
from .update import run_update

_console = Console()

_session_manager = SessionManager()


def _run_non_interactive(prompt: str) -> None:
    transcript = Transcript(
        system=SYSTEM,
        tools=TOOLS,
        messages=[UserMessage(content=prompt)],
    )
    session_id = _session_manager.new_id()
    history_len = len(transcript.messages)
    agent_loop(transcript, session_id)
    if len(transcript.messages) > history_len:
        _session_manager.save(session_id, transcript.messages)


def _run_interactive(prompt: str | None = None, session_id: str | None = None) -> None:
    print_welcome_banner()
    if config.get_provider().auth_type == "chatgpt" and not is_logged_in():
        print("ChatGPT is not signed in. Run /login.\n")
    print_mcp_hint()
    history: list[Message] = []
    transcript = Transcript(system=SYSTEM, tools=TOOLS, messages=history)
    current_session_id = _session_manager.new_id()
    session, pre_run, attached_images, sent_image_count = build_session(
        lambda: history, prompt
    )

    if session_id is not None:
        current_session_id = session_id
        sessions = _session_manager.list_sessions()
        try:
            chosen = next(
                stored for stored in sessions if stored.session_id == current_session_id
            )
            history = chosen.history.copy()
            transcript.messages = history
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
            transcript.messages = history
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
        if command == "/login":
            try:
                record = login()
            except ChatGPTAuthError as error:
                print(f"{error}\n")
                attached_images.clear()
                continue
            config.set_session_provider("chatgpt")
            print(f"Signed in to ChatGPT as {record.label}.\n")
            try:
                models = _fetch_models()
            except Exception as error:
                print(f"Could not fetch ChatGPT models: {error}\n")
            else:
                if config.get_model() not in models:
                    prompt_model()
            attached_images.clear()
            continue
        if command == "/logout":
            warning = logout()
            if warning:
                print(f"{warning}\n")
            else:
                print("Signed out of ChatGPT.\n")
            if config.get_provider().auth_type == "chatgpt":
                for provider in config.get_providers():
                    if provider.auth_type != "chatgpt":
                        config.set_session_provider(provider.id)
                        print(f"Provider set to {provider.name}.\n")
                        break
            attached_images.clear()
            continue
        if command == "/status":
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
            prompt_mcp()
            attached_images.clear()
            continue

        content = build_user_content(query, attached_images, sent_image_count)

        history.append(UserMessage(content=content))
        history_len = len(history)
        agent_loop(transcript, current_session_id)

        if len(history) <= history_len:
            continue
        _session_manager.save(current_session_id, history)

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

    mcp_lines = setup_mcp()
    if mcp_lines:
        for line in mcp_lines:
            _console.print(line, style=LIGHT_HINT_STYLE_RICH)
        print()

    try:
        if args.print_prompt:
            _run_non_interactive(args.print_prompt)
            return

        session_id: str | None = args.session_id
        if session_id == "__LATEST__":
            sessions = _session_manager.list_sessions()
            if sessions:
                session_id = sessions[0].session_id
            else:
                print("No saved sessions found.")
                return

        _run_interactive(args.prompt, session_id)
    finally:
        shutdown_mcp()
