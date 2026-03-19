import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_API_KEY", None)

WORKDIR = Path.cwd()
MODEL = os.environ["MODEL_ID"]
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
