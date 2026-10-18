import tomllib
from pathlib import Path

import pytest

from mini_agent.config import _build_client, _Config, get_client

PROVIDERS_TOML = """
provider = "deepseek"

[providers.colorist]
name = "Colorist Staging"
base_url = "https://colorist.example.com"
api_key_env = "COLORIST_API_KEY"

[providers.deepseek]
name = "DeepSeek"
base_url = "https://api.deepseek.com/anthropic"
api_key_env = "DEEPSEEK_API_KEY"
"""


def test_get_model() -> None:
    config = _Config()
    config.save_model(model_id="deepseek-v4-flash")
    assert config.get_model() == "deepseek-v4-flash"


def test_client_uses_selected_provider_and_its_api_key(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file.write_text(PROVIDERS_TOML)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setattr("mini_agent.config.config", _Config())

    client = get_client()

    assert str(client.base_url) == "https://api.deepseek.com/anthropic/"
    assert client.auth_token == "deepseek-key"


def test_session_provider_does_not_persist(config_file: Path) -> None:
    config_file.write_text(PROVIDERS_TOML)
    config = _Config()

    config.set_session_provider("colorist")

    assert config.get_provider().name == "Colorist Staging"
    assert _Config().get_provider().name == "DeepSeek"


def test_save_provider_keeps_provider_tables(config_file: Path) -> None:
    config_file.write_text(PROVIDERS_TOML)

    _Config().save_provider("colorist")

    saved = tomllib.loads(config_file.read_text())
    assert saved["provider"] == "colorist"
    assert saved["providers"]["deepseek"]["name"] == "DeepSeek"


def test_unknown_provider_is_rejected(config_file: Path) -> None:
    config_file.write_text(PROVIDERS_TOML)
    config = _Config()

    config.set_session_provider("Colorist Staging")

    with pytest.raises(ValueError, match="Unknown provider: Colorist Staging"):
        config.get_provider()


def test_missing_api_key_is_reported(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file.write_text(PROVIDERS_TOML)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr("mini_agent.config.config", _Config())
    _build_client.cache_clear()

    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY is not set for DeepSeek"):
        get_client()
