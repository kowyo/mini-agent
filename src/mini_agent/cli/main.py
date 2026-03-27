import uuid

from anthropic.types import MessageParam
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent

from ..agent.agent import agent_loop
from .display import (
    COMPLETION_STYLE,
    CommandCompleter,
    clear_terminal,
    get_token_usage,
    print_welcome_banner,
    reset_token_usage,
)
from .display.printing import get_status_toolbar
from .display.theme import PROMPT_ACCENT_COLOR
from .models import prompt_model
from .sessions import prompt_resume, save_session_history


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


def main() -> None:
    print_welcome_banner()
    history: list[MessageParam] = []
    current_session_id = uuid.uuid4().hex
    session = build_session()

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
            reset_token_usage()
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

        save_session_history(current_session_id, history, get_token_usage())

        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(f"> {block.text}\n")
