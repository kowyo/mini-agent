import queue
import threading
import time
import uuid
from contextlib import suppress

from anthropic.types import MessageParam
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML, FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.patch_stdout import patch_stdout

from ..agent.agent import agent_loop
from .display import (
    COMPLETION_STYLE,
    LIGHT_HINT_STYLE,
    CommandCompleter,
    clear_terminal,
    print_welcome_banner,
)
from .display.printing import get_status_toolbar
from .display.theme import PROMPT_ACCENT_COLOR
from .models import prompt_model
from .sessions import prompt_resume, save_session_history


def build_session(agent_running: threading.Event) -> tuple[PromptSession, object]:
    bindings = KeyBindings()
    last_ctrl_c = 0.0
    hint_refresh_timer: threading.Timer | None = None
    exit_sentinel = object()
    ctrl_c_timeout = 1.0
    _hint_text = FormattedText([(LIGHT_HINT_STYLE, "  Press Ctrl-C again to exit")])

    def status_toolbar() -> FormattedText:
        if time.monotonic() < last_ctrl_c + ctrl_c_timeout:
            return _hint_text
        return get_status_toolbar()

    @bindings.add("c-c")
    def clear_buffer(event: KeyPressEvent) -> None:
        nonlocal last_ctrl_c, hint_refresh_timer

        now = time.monotonic()
        if now - last_ctrl_c <= ctrl_c_timeout:
            if hint_refresh_timer is not None:
                hint_refresh_timer.cancel()
            event.app.exit(result=exit_sentinel)
            return

        last_ctrl_c = now
        event.current_buffer.reset()
        event.app.invalidate()

        if hint_refresh_timer is not None:
            hint_refresh_timer.cancel()

        hint_refresh_timer = threading.Timer(ctrl_c_timeout, event.app.invalidate)
        hint_refresh_timer.daemon = True
        hint_refresh_timer.start()

    @bindings.add("enter")
    def submit(event: KeyPressEvent) -> None:
        event.current_buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    def insert_newline(event: KeyPressEvent) -> None:
        event.current_buffer.insert_text("\n")

    return (
        PromptSession(
            HTML(f'<style color="{PROMPT_ACCENT_COLOR}">> </style>'),
            multiline=True,
            key_bindings=bindings,
            completer=CommandCompleter(),
            complete_while_typing=True,
            style=COMPLETION_STYLE,
            bottom_toolbar=status_toolbar,
            reserve_space_for_menu=2,
        ),
        exit_sentinel,
    )


def main() -> None:
    print_welcome_banner()
    history: list[MessageParam] = []
    current_session_id = uuid.uuid4().hex
    agent_running = threading.Event()
    session, exit_sentinel = build_session(agent_running)
    msg_queue: queue.Queue[str | None] = queue.Queue()

    def agent_worker() -> None:
        nonlocal current_session_id
        while True:
            query = msg_queue.get()
            if query is None:
                break

            agent_running.set()
            with suppress(Exception):
                session.app.invalidate()

            history.append({"role": "user", "content": query})
            history_len = len(history)
            agent_loop(history)

            if len(history) > history_len:
                save_session_history(current_session_id, history)
                response_content = history[-1]["content"]
                if isinstance(response_content, list):
                    for block in response_content:
                        if hasattr(block, "text"):
                            print(f"> {block.text}\n")

            agent_running.clear()
            with suppress(Exception):
                session.app.invalidate()

    worker = threading.Thread(target=agent_worker, daemon=True)
    worker.start()

    with patch_stdout(raw=True):
        while True:
            try:
                query = session.prompt()
                print()
            except KeyboardInterrupt:
                continue
            except EOFError:
                break

            if query is exit_sentinel:
                break

            command = query.strip().lower()
            if command in {"", "q", "exit"}:
                break
            if command == "/new":
                history.clear()
                current_session_id = uuid.uuid4().hex
                clear_terminal()
                continue
            if command == "/resume":
                current_session_id, history = prompt_resume(current_session_id, history)
                continue
            if command == "/model":
                prompt_model()
                continue

            msg_queue.put(query)

    msg_queue.put(None)
    worker.join(timeout=5)
