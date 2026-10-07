from collections.abc import Iterator
from types import TracebackType
from typing import Protocol

from .types import AssistantTurn, Message, StreamEvent, ToolSpec


class MessageStream(Protocol):
    def __enter__(self) -> MessageStream: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    def __iter__(self) -> Iterator[StreamEvent]: ...

    def get_final_turn(self) -> AssistantTurn: ...


class Provider(Protocol):
    def stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        effort: str,
        cache_control: bool,
        max_tokens: int,
    ) -> MessageStream: ...

    def list_models(self) -> list[str]: ...
