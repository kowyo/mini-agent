class Token:
    def __init__(self) -> None:
        self._last_usage: tuple[int, int] | None = None

    def update(self, input_tokens: int, output_tokens: int) -> None:
        self._last_usage = (input_tokens, output_tokens)

    def reset(self) -> None:
        self._last_usage = None

    def get(self) -> tuple[int, int] | None:
        return self._last_usage


token = Token()
