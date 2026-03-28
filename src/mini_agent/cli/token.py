class TokenTracker:
    def __init__(self) -> None:
        self._total_usage: tuple[int, int] | None = None
        self._last_round: tuple[int, int] | None = None

    def update(self, input_tokens: int, output_tokens: int) -> None:
        self._last_round = (input_tokens, output_tokens)
        if self._total_usage is None:
            self._total_usage = (input_tokens, output_tokens)
        else:
            self._total_usage = (
                self._total_usage[0] + input_tokens,
                self._total_usage[1] + output_tokens,
            )

    def restore(self, total_usage: tuple[int, int]) -> None:
        self._total_usage = total_usage
        self._last_round = None

    def reset(self) -> None:
        self._total_usage = None
        self._last_round = None

    def get(self) -> tuple[int, int] | None:
        return self._total_usage

    def get_last_round(self) -> tuple[int, int] | None:
        return self._last_round


token_tracker = TokenTracker()
