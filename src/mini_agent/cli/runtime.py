import queue
import threading
import uuid
from contextlib import suppress
from dataclasses import dataclass, field

from anthropic.types import MessageParam
from prompt_toolkit import PromptSession

from ..agent.agent import agent_loop
from .sessions import save_session_history


def new_session_id() -> str:
    return uuid.uuid4().hex


@dataclass(slots=True)
class ConversationState:
    history: list[MessageParam] = field(default_factory=list)
    session_id: str = field(default_factory=new_session_id)


class BackgroundAgentRunner:
    def __init__(self, conversation: ConversationState) -> None:
        self._session: PromptSession | None = None
        self._conversation = conversation
        self._running = threading.Event()
        self._cancel = threading.Event()
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._pending_requests = 0
        self._pending_lock = threading.Lock()
        self._worker: threading.Thread | None = None

    @property
    def running_event(self) -> threading.Event:
        return self._running

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel

    def submit(self, query: str) -> None:
        with self._pending_lock:
            self._pending_requests += 1
        self._queue.put(query)

    def attach_session(self, session: PromptSession) -> None:
        self._session = session

    def start(self) -> None:
        if self._worker is not None:
            return

        self._worker = threading.Thread(target=self._agent_worker, daemon=True)
        self._worker.start()

    def interrupt(self) -> None:
        self._cancel.set()

    def is_busy(self) -> bool:
        with self._pending_lock:
            return self._pending_requests > 0

    def stop(self, timeout: float = 5.0) -> None:
        if self._worker is None:
            return

        self._cancel.set()
        self._drain_queue()
        self._queue.put(None)
        self._worker.join(timeout=timeout)

    def _agent_worker(self) -> None:
        while True:
            query = self._queue.get()
            if query is None:
                break

            self._running.set()
            self._invalidate_session()

            try:
                history = self._conversation.history
                history.append({"role": "user", "content": query})
                history_len = len(history)
                agent_loop(history, cancel=self._cancel)
                self._cancel.clear()

                if len(history) > history_len:
                    save_session_history(self._conversation.session_id, history)
                    self._print_response(history[-1]["content"])
            except Exception as e:
                print(f"Error: {e}\n")
            finally:
                self._cancel.clear()
                self._running.clear()
                self._mark_request_complete()
                self._invalidate_session()

    def _drain_queue(self) -> None:
        while True:
            try:
                query = self._queue.get_nowait()
            except queue.Empty:
                return

            if query is not None:
                self._mark_request_complete()

    def _mark_request_complete(self) -> None:
        with self._pending_lock:
            self._pending_requests = max(self._pending_requests - 1, 0)

    def _invalidate_session(self) -> None:
        if self._session is None:
            return
        with suppress(Exception):
            self._session.app.invalidate()

    @staticmethod
    def _print_response(content: object) -> None:
        if not isinstance(content, list):
            return

        for block in content:
            if hasattr(block, "text"):
                print(f"> {block.text}\n")
