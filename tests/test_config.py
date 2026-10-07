from pathlib import Path

import pytest

from mini_agent import config as config_module
from mini_agent.config import Config


def test_get_model() -> None:
    config = Config()
    config.save_model(model_id="deepseek-v4-flash")
    assert config.get_model() == "deepseek-v4-flash"


def test_get_provider_defaults_to_anthropic_messages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config_module, "CONFIG_FILE", tmp_path / "config.toml")

    assert Config().get_provider() == "anthropic-messages"


def test_get_provider_reads_config_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text('provider = "openai-responses"\n')
    monkeypatch.setattr(config_module, "CONFIG_FILE", config_file)

    assert Config().get_provider() == "openai-responses"
