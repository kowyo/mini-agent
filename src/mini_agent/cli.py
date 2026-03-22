import os
import subprocess
import uuid

from anthropic.types import MessageParam
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent

from .agent import agent_loop
from .display import COMPLETION_STYLE, CommandCompleter, print_welcome_banner
from .sessions import prompt_resume, save_session_history


def clear_terminal() -> None:
    subprocess.run(
        ["cls" if os.name == "nt" else "clear"],
        check=False,
    )


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
        HTML('<style color="#87CEEB">> </style>'),
        multiline=True,
        key_bindings=bindings,
        completer=CommandCompleter(),
        complete_while_typing=True,
        style=COMPLETION_STYLE,
    )


def main() -> None:
    clear_terminal()
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
            clear_terminal()
            print_welcome_banner()
            continue
        if command == "/resume":
            current_session_id, history = prompt_resume(
                session, current_session_id, history, clear_terminal
            )
            continue

        history.append({"role": "user", "content": query})
        agent_loop(history)
        save_session_history(current_session_id, history)

        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(f"> {block.text}\n")
