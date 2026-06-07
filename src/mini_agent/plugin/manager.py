"""Plugin discovery and lifecycle dispatch."""

import contextlib
import importlib.metadata
import warnings
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PluginManager:
    """Discovers plugins and dispatches lifecycle events."""

    plugins: list[Any] = field(default_factory=list)

    @staticmethod
    def discover() -> PluginManager:
        plugins: list[Any] = []
        for ep in importlib.metadata.entry_points(group="mini_agent.plugins"):
            try:
                plugins.append(ep.load()())
            except Exception as exc:
                warnings.warn(f"Failed to load plugin '{ep.name}': {exc}", stacklevel=2)
        return PluginManager(plugins=plugins)

    def on_agent_init(self) -> None:
        for p in self.plugins:
            with contextlib.suppress(Exception):
                p.on_agent_init()

    def on_session_start(self, session_id: str) -> None:
        for p in self.plugins:
            with contextlib.suppress(Exception):
                p.on_session_start(session_id)

    def on_turn_complete(
        self,
        session_id: str,
        history: list[dict[str, Any]],
        round_usages: list[Any] | None,
    ) -> None:
        for p in self.plugins:
            with contextlib.suppress(Exception):
                p.on_turn_complete(session_id, history, round_usages)

    def on_session_end(
        self,
        session_id: str,
        history: list[dict[str, Any]],
        round_usages: list[Any] | None,
    ) -> None:
        for p in self.plugins:
            with contextlib.suppress(Exception):
                p.on_session_end(session_id, history, round_usages)

    def list_plugins(self) -> list[str]:
        return [type(p).__name__ for p in self.plugins]
