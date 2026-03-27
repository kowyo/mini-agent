import threading
import time
from enum import Enum, auto

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML, FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent

from .display import COMPLETION_STYLE, LIGHT_HINT_STYLE, CommandCompleter
from .display.printing import get_status_toolbar
from .display.theme import PROMPT_ACCENT_COLOR


class SessionSignal(Enum):
    EXIT = auto()


class CtrlCBehavior:
    def __init__(
        self,
        agent_running: threading.Event,
        cancel: threading.Event,
        timeout_seconds: float = 1.0,
    ) -> None:
        self._agent_running = agent_running
        self._cancel = cancel
        self._timeout_seconds = timeout_seconds
        self._last_press_at = 0.0
        self._hint_refresh_timer: threading.Timer | None = None
        self._hint_text = FormattedText(
            [(LIGHT_HINT_STYLE, "  Press Ctrl-C again to exit")]
        )

    def bottom_toolbar(self) -> FormattedText:
        if time.monotonic() < self._last_press_at + self._timeout_seconds:
            return self._hint_text
        return get_status_toolbar()

    def handle(self, event: KeyPressEvent) -> None:
        if self._agent_running.is_set():
            self._cancel.set()
            return

        now = time.monotonic()
        if now - self._last_press_at <= self._timeout_seconds:
            self.dispose()
            event.app.exit(result=SessionSignal.EXIT)
            return

        self._last_press_at = now
        event.current_buffer.reset()
        event.app.invalidate()
        self._schedule_hint_refresh(event)

    def dispose(self) -> None:
        if self._hint_refresh_timer is None:
            return
        self._hint_refresh_timer.cancel()
        self._hint_refresh_timer = None

    def _schedule_hint_refresh(self, event: KeyPressEvent) -> None:
        self.dispose()
        self._hint_refresh_timer = threading.Timer(
            self._timeout_seconds,
            event.app.invalidate,
        )
        self._hint_refresh_timer.daemon = True
        self._hint_refresh_timer.start()


def build_session(
    agent_running: threading.Event,
    cancel: threading.Event,
) -> tuple[PromptSession, CtrlCBehavior]:
    bindings = KeyBindings()
    ctrl_c_behavior = CtrlCBehavior(agent_running, cancel)

    @bindings.add("c-c")
    def handle_ctrl_c(event: KeyPressEvent) -> None:
        ctrl_c_behavior.handle(event)

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
        bottom_toolbar=ctrl_c_behavior.bottom_toolbar,
        reserve_space_for_menu=3,
    )
    return session, ctrl_c_behavior
