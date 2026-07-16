from dataclasses import dataclass


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    output_tokens: int

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens
            + other.cache_creation_input_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens
            + other.cache_read_input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )

    @property
    def total_input_tokens(self) -> int:
        return (
            self.input_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )

    @property
    def cache_hit_rate(self) -> float:
        total = self.total_input_tokens
        return self.cache_read_input_tokens / total if total else 0.0


class TokenTracker:
    """Tracks per-round token usage and computes accumulated totals."""

    def __init__(self) -> None:
        """Initialize with empty usage history."""
        self.round_usages: list[Usage] = []
        self.total_usage: Usage | None = None
        self.last_round: Usage | None = None

    def update(self, usage: Usage) -> None:
        self.round_usages.append(usage)
        self.last_round = usage
        if self.total_usage is None:
            self.total_usage = usage
        else:
            self.total_usage = self.total_usage + usage

    def restore(self, round_usages: list[Usage]) -> None:
        self.round_usages = list(round_usages)
        if round_usages:
            self.total_usage = sum(round_usages[1:], start=round_usages[0])
        else:
            self.total_usage = None
        self.last_round = round_usages[-1] if round_usages else None

    def reset(self) -> None:
        """Clear all tracked usage data."""
        self.round_usages.clear()
        self.total_usage = None
        self.last_round = None

    def get(self) -> Usage | None:
        """Return the accumulated total usage, or None if no rounds recorded."""
        return self.total_usage

    def get_last_round(self) -> Usage | None:
        """Return the most recent round's usage, or None if no rounds recorded."""
        return self.last_round


token_tracker = TokenTracker()
