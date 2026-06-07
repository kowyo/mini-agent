"""Base class for mini-agent plugins.

Zero internal dependencies — safe to import before the rest of
the mini-agent package is fully initialised.
"""

from typing import Any


class MiniAgentPlugin:
    """Override lifecycle methods as needed. All default to no-ops."""

    def on_agent_init(self) -> None: ...
    def on_session_start(self, session_id: str) -> None: ...
    def on_turn_complete(
        self,
        session_id: str,
        history: list[dict[str, Any]],
        round_usages: list[Any] | None,
    ) -> None: ...
    def on_session_end(
        self,
        session_id: str,
        history: list[dict[str, Any]],
        round_usages: list[Any] | None,
    ) -> None: ...
