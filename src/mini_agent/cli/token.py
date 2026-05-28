from dataclasses import dataclass


@dataclass(frozen=True)
class Usage:
    """Token counts for one assistant response round."""

    input_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    output_tokens: int

    @property
    def total_input_tokens(self) -> int:
        """Sum of all input-side token counts."""
        return (
            self.input_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )


class TokenTracker:
    """Tracks per-round token usage and computes accumulated totals."""

    def __init__(self) -> None:
        """Initialize with empty usage history."""
        self.round_usages: list[Usage] = []
        self.total_usage: Usage | None = None
        self.last_round: Usage | None = None

    def update(self, usage: Usage) -> None:
        """Record a new round's usage and update accumulated total."""
        self.round_usages.append(usage)
        self.last_round = usage
        if self.total_usage is None:
            self.total_usage = usage
        else:
            self.total_usage = Usage(
                input_tokens=self.total_usage.input_tokens + usage.input_tokens,
                cache_creation_input_tokens=self.total_usage.cache_creation_input_tokens
                + usage.cache_creation_input_tokens,
                cache_read_input_tokens=self.total_usage.cache_read_input_tokens
                + usage.cache_read_input_tokens,
                output_tokens=self.total_usage.output_tokens + usage.output_tokens,
            )

    def restore(self, round_usages: list[Usage]) -> None:
        """Restore state from a list of per-round usages, computing the total."""
        self.round_usages = list(round_usages)
        total: Usage | None = None
        for u in round_usages:
            total = (
                u
                if total is None
                else Usage(
                    input_tokens=total.input_tokens + u.input_tokens,
                    cache_creation_input_tokens=total.cache_creation_input_tokens
                    + u.cache_creation_input_tokens,
                    cache_read_input_tokens=total.cache_read_input_tokens
                    + u.cache_read_input_tokens,
                    output_tokens=total.output_tokens + u.output_tokens,
                )
            )
        self.total_usage = total
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
