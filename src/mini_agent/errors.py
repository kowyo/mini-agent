from .config import CONFIG_DIR


class APIKeyMissingError(Exception):
    """Raised when no API key is configured."""

    def __init__(self) -> None:
        super().__init__(
            "API key not set. Either:\n"
            "1. export ANTHROPIC_API_KEY=sk-...\n"
            f"2. Save it to {CONFIG_DIR / '.env'} as ANTHROPIC_API_KEY=sk-..."
        )
