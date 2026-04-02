import importlib.metadata
import os
import tomllib
from pathlib import Path

import tomli_w
from anthropic import Anthropic
from dotenv import load_dotenv

DEFAULT_CONFIG_DIR = Path.home() / ".mini-agent"
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_REASONING_EFFORT = "medium"
REASONING_EFFORT_LEVELS = ["none", "low", "medium", "high"]
REASONING_BUDGET_TOKENS: dict[str, int | None] = {
    "none": None,
    "low": 1024,
    "medium": 6000,
    "high": 16000,
}
CONFIG_DIR = DEFAULT_CONFIG_DIR
SESSION_DIR = CONFIG_DIR / "sessions"
CONFIG_FILE = CONFIG_DIR / "config.toml"

WORKDIR = Path.cwd()
HOME_SKILLS_DIR = Path.home() / ".agents" / "skills"
PROJECT_SKILLS_DIR = WORKDIR / ".agents" / "skills"
SKILLS_DIRS = [HOME_SKILLS_DIR, PROJECT_SKILLS_DIR]

load_dotenv(CONFIG_DIR / ".env")

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_API_KEY", None)

client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))


class Config:
    def __init__(self) -> None:
        self._model: str | None = None
        self._session_model_override: str | None = None
        self._reasoning_effort: str | None = None
        self._session_reasoning_effort_override: str | None = None

    def _load_config(self) -> dict[str, object]:
        if CONFIG_FILE.exists():
            return tomllib.loads(CONFIG_FILE.read_text())
        return {}

    def set_session_model(self, model_id: str) -> None:
        self._session_model_override = model_id

    def get_model(self) -> str:
        if self._session_model_override is not None:
            return self._session_model_override
        if self._model is None:
            cfg = self._load_config()
            self._model = str(cfg.get("model_id", DEFAULT_MODEL))
        return self._model

    def save_model(self, model_id: str) -> None:
        self._session_model_override = None
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cfg = self._load_config()
        cfg["model_id"] = model_id
        CONFIG_FILE.write_text(tomli_w.dumps(cfg))
        self._model = model_id

    def set_session_reasoning_effort(self, effort: str) -> None:
        self._session_reasoning_effort_override = effort

    def get_reasoning_effort(self) -> str:
        if self._session_reasoning_effort_override is not None:
            return self._session_reasoning_effort_override
        if self._reasoning_effort is None:
            cfg = self._load_config()
            self._reasoning_effort = str(
                cfg.get("reasoning_effort", DEFAULT_REASONING_EFFORT)
            )
        return self._reasoning_effort

    def save_reasoning_effort(self, effort: str) -> None:
        self._session_reasoning_effort_override = None
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cfg = self._load_config()
        cfg["reasoning_effort"] = effort
        CONFIG_FILE.write_text(tomli_w.dumps(cfg))
        self._reasoning_effort = effort


config = Config()


CLI_NAME = "mini-agent"
CLI_VERSION = importlib.metadata.version(CLI_NAME)
