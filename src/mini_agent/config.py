import importlib.metadata
import os
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import cast

import tomli_w
from anthropic import Anthropic
from dotenv import load_dotenv
from openai import OpenAI

DISTRIBUTION_NAME = "mini-agent"
DISTRIBUTION_VERSION = importlib.metadata.version(DISTRIBUTION_NAME)

_DEFAULT_CONFIG_DIR = Path.home() / ".mini-agent"
_DEFAULT_MODEL = "claude-sonnet-4-6"
_DEFAULT_REASONING_EFFORT = "high"
REASONING_EFFORT_LEVELS = [
    "disabled",
    "adaptive",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
]
API_TYPES = ("message", "response")
CONFIG_DIR = _DEFAULT_CONFIG_DIR
SESSION_DIR = CONFIG_DIR / "sessions"
_CONFIG_FILE = CONFIG_DIR / "config.toml"

WORKDIR = Path.cwd()
_HOME_SKILLS_DIR = Path.home() / ".agents" / "skills"
_HOME_MINI_AGENT_SKILLS_DIR = Path.home() / ".mini-agent" / "skills"
_PROJECT_SKILLS_DIR = WORKDIR / ".agents" / "skills"
_PROJECT_MINI_AGENT_SKILLS_DIR = WORKDIR / ".mini-agent" / "skills"
SKILLS_DIRS = [
    _HOME_SKILLS_DIR,
    _HOME_MINI_AGENT_SKILLS_DIR,
    _PROJECT_SKILLS_DIR,
    _PROJECT_MINI_AGENT_SKILLS_DIR,
]

load_dotenv(CONFIG_DIR / ".env")


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    base_url: str
    api_key_env: str | None = None
    api_type: str = "message"


class _Config:
    def __init__(self) -> None:
        self._model: str | None = None
        self._session_model_override: str | None = None
        self._reasoning_effort: str | None = None
        self._session_reasoning_effort_override: str | None = None
        self._providers: dict[str, Provider] | None = None
        self._provider_id: str | None = None
        self._session_provider_override: str | None = None

    def _load_config(self) -> dict[str, object]:
        if _CONFIG_FILE.exists():
            return tomllib.loads(_CONFIG_FILE.read_text())
        return {}

    def set_session_model(self, model_id: str) -> None:
        self._session_model_override = model_id

    def get_model(self) -> str:
        if self._session_model_override is not None:
            return self._session_model_override
        if self._model is None:
            cfg = self._load_config()
            self._model = str(cfg.get("model_id", _DEFAULT_MODEL))
        return self._model

    def save_model(self, model_id: str) -> None:
        self._session_model_override = None
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cfg = self._load_config()
        cfg["model_id"] = model_id
        _CONFIG_FILE.write_text(tomli_w.dumps(cfg))
        self._model = model_id

    def set_session_reasoning_effort(self, effort: str) -> None:
        self._session_reasoning_effort_override = effort

    def get_reasoning_effort(self) -> str:
        if self._session_reasoning_effort_override is not None:
            return self._session_reasoning_effort_override
        if self._reasoning_effort is None:
            cfg = self._load_config()
            self._reasoning_effort = str(
                cfg.get("reasoning_effort", _DEFAULT_REASONING_EFFORT)
            )
        return self._reasoning_effort

    def save_reasoning_effort(self, effort: str) -> None:
        self._session_reasoning_effort_override = None
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cfg = self._load_config()
        cfg["reasoning_effort"] = effort
        _CONFIG_FILE.write_text(tomli_w.dumps(cfg))
        self._reasoning_effort = effort

    def get_providers(self) -> list[Provider]:
        if self._providers is None:
            tables = cast(
                dict[str, dict[str, object]], self._load_config().get("providers", {})
            )
            self._providers = {}
            for provider_id, table in tables.items():
                try:
                    api_type = str(table.get("api_type", "message"))
                    if api_type not in API_TYPES:
                        raise ValueError(
                            f"providers.{provider_id}.api_type must be one of "
                            f"{', '.join(API_TYPES)}"
                        )
                    self._providers[provider_id] = Provider(
                        id=provider_id,
                        name=str(table["name"]),
                        base_url=str(table["base_url"]),
                        api_key_env=(
                            str(table["api_key_env"])
                            if "api_key_env" in table
                            else None
                        ),
                        api_type=api_type,
                    )
                except KeyError as e:
                    raise ValueError(
                        f"providers.{provider_id} in {_CONFIG_FILE} is missing {e}"
                    ) from None
        return list(self._providers.values())

    def set_session_provider(self, provider_id: str) -> None:
        self._session_provider_override = provider_id

    def get_provider(self) -> Provider:
        providers = {provider.id: provider for provider in self.get_providers()}
        if not providers:
            raise ValueError(f"No providers configured in {_CONFIG_FILE}")
        if self._provider_id is None:
            saved = self._load_config().get("provider")
            self._provider_id = str(saved) if saved else next(iter(providers))
        provider_id = self._session_provider_override or self._provider_id
        if provider_id not in providers:
            raise ValueError(f"Unknown provider: {provider_id}")
        return providers[provider_id]

    def save_provider(self, provider_id: str) -> None:
        self._session_provider_override = None
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cfg = self._load_config()
        cfg["provider"] = provider_id
        _CONFIG_FILE.write_text(tomli_w.dumps(cfg))
        self._provider_id = provider_id


config = _Config()


def get_api_key(provider: Provider) -> str:
    if provider.api_key_env is None:
        raise ValueError(f"No API key configured for {provider.name}")
    api_key = os.getenv(provider.api_key_env)
    if not api_key:
        raise ValueError(f"{provider.api_key_env} is not set for {provider.name}")
    return api_key


@cache
def _build_client(provider: Provider) -> Anthropic:
    return Anthropic(base_url=provider.base_url, auth_token=get_api_key(provider))


@cache
def _build_responses_client(provider: Provider) -> OpenAI:
    return OpenAI(
        api_key=get_api_key(provider),
        base_url=provider.base_url,
        max_retries=0,
    )


def get_client() -> Anthropic:
    provider = config.get_provider()
    if provider.api_type != "message":
        raise ValueError(f"{provider.name} does not use the message API")
    return _build_client(provider)


def get_responses_client() -> OpenAI:
    provider = config.get_provider()
    if provider.api_type != "response":
        raise ValueError(f"{provider.name} does not use the response API")
    return _build_responses_client(provider)
