from collections.abc import Callable
from pathlib import Path

import pytest

from mini_agent import config

TERMINAL_ENV_VARS = (
    "TERM",
    "TERM_PROGRAM",
    "TMUX",
    "KITTY_WINDOW_ID",
    "GHOSTTY_RESOURCES_DIR",
    "WEZTERM_PANE",
    "ITERM_SESSION_ID",
)


@pytest.fixture(autouse=True)
def terminal_env(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    for name in TERMINAL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    def set_env(**variables: str) -> None:
        for name, value in variables.items():
            monkeypatch.setenv(name, value)

    return set_env


@pytest.fixture(autouse=True)
def config_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", path)
    return path
