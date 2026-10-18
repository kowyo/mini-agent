from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from ...config import Provider
from ..transcript import AssistantMessage, Transcript


class ApiError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class TurnRequest:
    transcript: Transcript
    provider: Provider
    model: str
    reasoning_effort: str
    session_id: str | None
    max_output_tokens: int | None


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ThinkingDelta:
    text: str


@dataclass(frozen=True)
class BlockEnd:
    pass


StreamEvent = TextDelta | ThinkingDelta | BlockEnd


class TurnStream(Protocol):
    def __enter__(self) -> TurnStream: ...

    def __exit__(self, *args: object) -> None: ...

    def __iter__(self) -> Iterator[StreamEvent]: ...

    def get_final_message(self) -> AssistantMessage: ...


class ApiBackend(Protocol):
    def run_turn(self, request: TurnRequest) -> TurnStream: ...
