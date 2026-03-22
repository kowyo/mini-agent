import importlib.metadata
import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

WORKDIR = Path.cwd()
DEFAULT_CONFIG_DIR = Path.home() / ".mini-agent"
load_dotenv(DEFAULT_CONFIG_DIR / ".env")

CONFIG_DIR = Path(os.getenv("CONFIG_DIR", DEFAULT_CONFIG_DIR)).expanduser()
SESSION_DIR = CONFIG_DIR / "sessions"

load_dotenv(CONFIG_DIR / ".env", override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_API_KEY", None)

MODEL = os.environ["MODEL_ID"]
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))

CLI_NAME = "mini-agent"
CLI_VERSION = importlib.metadata.version(CLI_NAME)
