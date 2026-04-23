from dataclasses import dataclass


@dataclass
class Usage:
    input_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    output_tokens: int

    @property
    def total_input_tokens(self) -> int:
        return (
            self.input_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )


class TokenTracker:
    def __init__(self) -> None:
        self._total_usage: Usage | None = None
        self._last_round: Usage | None = None

    def update(self, usage: Usage) -> None:
        self._last_round = usage
        if self._total_usage is None:
            self._total_usage = usage
        else:
            self._total_usage = Usage(
                input_tokens=self._total_usage.input_tokens + usage.input_tokens,
                cache_creation_input_tokens=self._total_usage.cache_creation_input_tokens
                + usage.cache_creation_input_tokens,
                cache_read_input_tokens=self._total_usage.cache_read_input_tokens
                + usage.cache_read_input_tokens,
                output_tokens=self._total_usage.output_tokens + usage.output_tokens,
            )

    def restore(self, total_usage: Usage) -> None:
        self._total_usage = total_usage
        self._last_round = None

    def reset(self) -> None:
        self._total_usage = None
        self._last_round = None

    def get(self) -> Usage | None:
        return self._total_usage

    def get_last_round(self) -> Usage | None:
        return self._last_round


token_tracker = TokenTracker()
