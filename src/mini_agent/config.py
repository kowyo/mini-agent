import importlib.metadata
import os
import tomllib
from pathlib import Path

import tomli_w
from anthropic import Anthropic
from dotenv import load_dotenv

WORKDIR = Path.cwd()
DEFAULT_CONFIG_DIR = Path.home() / ".mini-agent"
DEFAULT_MODEL = "claude-sonnet-4-6"
CONFIG_DIR = DEFAULT_CONFIG_DIR
SESSION_DIR = CONFIG_DIR / "sessions"
CONFIG_FILE = CONFIG_DIR / "config.toml"
load_dotenv(CONFIG_DIR / ".env")

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_API_KEY", None)

client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))

_model: str | None = None


def _load_config() -> dict[str, object]:
    if CONFIG_FILE.exists():
        return tomllib.loads(CONFIG_FILE.read_text())
    return {}


def get_model() -> str:
    global _model
    if _model is None:
        config = _load_config()
        _model = str(config.get("model_id", DEFAULT_MODEL))
    return _model


def save_model(model_id: str) -> None:
    global _model
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config = _load_config()
    config["model_id"] = model_id
    CONFIG_FILE.write_text(tomli_w.dumps(config))
    _model = model_id


CLI_NAME = "mini-agent"
CLI_VERSION = importlib.metadata.version(CLI_NAME)
