import importlib.metadata
import os
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .chatgpt import ChatGPTClient

import tomli_w
from anthropic import Anthropic
from dotenv import load_dotenv

DISTRIBUTION_NAME = "mini-agent"
DISTRIBUTION_VERSION = importlib.metadata.version(DISTRIBUTION_NAME)

DEFAULT_CONFIG_DIR = Path.home() / ".mini-agent"
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_CHATGPT_MODEL = "gpt-5.4"
DEFAULT_REASONING_EFFORT = "high"
REASONING_EFFORT_LEVELS = [
    "disabled",
    "adaptive",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
]
CONFIG_DIR = DEFAULT_CONFIG_DIR
SESSION_DIR = CONFIG_DIR / "sessions"
CONFIG_FILE = CONFIG_DIR / "config.toml"

WORKDIR = Path.cwd()
HOME_SKILLS_DIR = Path.home() / ".agents" / "skills"
HOME_MINI_AGENT_SKILLS_DIR = Path.home() / ".mini-agent" / "skills"
PROJECT_SKILLS_DIR = WORKDIR / ".agents" / "skills"
PROJECT_MINI_AGENT_SKILLS_DIR = WORKDIR / ".mini-agent" / "skills"
SKILLS_DIRS = [
    HOME_SKILLS_DIR,
    HOME_MINI_AGENT_SKILLS_DIR,
    PROJECT_SKILLS_DIR,
    PROJECT_MINI_AGENT_SKILLS_DIR,
]

load_dotenv(CONFIG_DIR / ".env")


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    base_url: str
    api_key_env: str


CHATGPT_PROVIDER = Provider(
    id="chatgpt",
    name="ChatGPT",
    base_url="https://chatgpt.com/backend-api/codex",
    api_key_env="",
)


class Config:
    def __init__(self) -> None:
        self._model: str | None = None
        self._session_model_override: str | None = None
        self._reasoning_effort: str | None = None
        self._session_reasoning_effort_override: str | None = None
        self._cache_control: bool | None = None
        self._providers: dict[str, Provider] | None = None
        self._provider_id: str | None = None
        self._session_provider_override: str | None = None

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

    def get_cache_control(self) -> bool:
        if self._cache_control is None:
            cfg = self._load_config()
            self._cache_control = bool(cfg.get("cache_control", False))
        return self._cache_control

    def save_reasoning_effort(self, effort: str) -> None:
        self._session_reasoning_effort_override = None
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cfg = self._load_config()
        cfg["reasoning_effort"] = effort
        CONFIG_FILE.write_text(tomli_w.dumps(cfg))
        self._reasoning_effort = effort

    def get_providers(self) -> list[Provider]:
        if self._providers is None:
            tables = cast(
                dict[str, dict[str, object]], self._load_config().get("providers", {})
            )
            self._providers = {}
            for provider_id, table in tables.items():
                if provider_id == CHATGPT_PROVIDER.id:
                    continue
                try:
                    self._providers[provider_id] = Provider(
                        id=provider_id,
                        name=str(table["name"]),
                        base_url=str(table["base_url"]),
                        api_key_env=str(table["api_key_env"]),
                    )
                except KeyError as e:
                    raise ValueError(
                        f"providers.{provider_id} in {CONFIG_FILE} is missing {e}"
                    ) from None
        return [*self._providers.values(), CHATGPT_PROVIDER]

    def set_session_provider(self, provider_id: str) -> None:
        self._session_provider_override = provider_id

    def get_provider(self) -> Provider:
        providers = {provider.id: provider for provider in self.get_providers()}
        if self._provider_id is None:
            saved = self._load_config().get("provider")
            configured = [p for p in providers if p != CHATGPT_PROVIDER.id]
            if not saved and not configured and not self._session_provider_override:
                raise ValueError(
                    f"No providers configured in {CONFIG_FILE}; run mini /login to use ChatGPT"
                )
            self._provider_id = str(saved) if saved else next(iter(configured), "")
        provider_id = self._session_provider_override or self._provider_id
        if provider_id not in providers:
            raise ValueError(f"Unknown provider: {provider_id}")
        return providers[provider_id]

    def save_provider_and_model(self, provider_id: str, model_id: str) -> None:
        """Persist a successful login's selection together, preserving other settings."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cfg = self._load_config()
        cfg["provider"] = provider_id
        cfg["model_id"] = model_id
        CONFIG_FILE.write_text(tomli_w.dumps(cfg))
        self._session_provider_override = None
        self._session_model_override = None
        self._provider_id = provider_id
        self._model = model_id

    def save_provider(self, provider_id: str) -> None:
        self._session_provider_override = None
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cfg = self._load_config()
        cfg["provider"] = provider_id
        CONFIG_FILE.write_text(tomli_w.dumps(cfg))
        self._provider_id = provider_id


config = Config()


@cache
def _build_client(provider: Provider) -> Anthropic:
    api_key = os.getenv(provider.api_key_env)
    if not api_key:
        raise ValueError(f"{provider.api_key_env} is not set for {provider.name}")
    return Anthropic(base_url=provider.base_url, auth_token=api_key)


def get_client() -> Anthropic | ChatGPTClient:
    provider = config.get_provider()
    if provider.id == CHATGPT_PROVIDER.id:
        from .chatgpt import ChatGPTClient

        return ChatGPTClient()
    return _build_client(provider)
