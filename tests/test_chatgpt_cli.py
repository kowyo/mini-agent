import importlib
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

from mini_agent import chatgpt, oauth
from mini_agent.cli import auth, models, providers
from mini_agent.cli.display.completion import COMMANDS
from mini_agent.config import DEFAULT_MODEL, Config, get_client

cli = importlib.import_module("mini_agent.cli.main")

_API_CONFIG = """
model_id = "existing-model"
reasoning_effort = "low"
[providers.gateway]
name = "Gateway"
base_url = "https://example.com"
api_key_env = "GATEWAY_API_KEY"
"""


def test_builtin_preserves_defaults_and_requires_explicit_selection() -> None:
    cfg = Config()
    assert [p.id for p in cfg.get_providers()] == ["chatgpt"]
    assert cfg.get_model() == DEFAULT_MODEL
    with pytest.raises(ValueError, match="No providers configured"):
        cfg.get_provider()
    cfg.set_session_provider("chatgpt")
    assert cfg.get_provider().id == "chatgpt"
    with pytest.raises(ValueError, match="No providers configured"):
        Config().get_provider()


def test_builtin_does_not_replace_first_api_provider(config_file: Path) -> None:
    config_file.write_text(_API_CONFIG)
    cfg = Config()
    assert cfg.get_provider().id == "gateway"
    assert [p.id for p in cfg.get_providers()] == ["gateway", "chatgpt"]


def test_chatgpt_client_needs_no_api_key(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file.write_text('provider = "chatgpt"\n')
    monkeypatch.setattr("mini_agent.config.config", Config())
    sentinel = object()
    monkeypatch.setattr(chatgpt, "ChatGPTClient", lambda: sentinel)

    def no_anthropic(*args: object, **kwargs: object) -> None:
        pytest.fail("ChatGPT must not construct an Anthropic client")

    monkeypatch.setattr("mini_agent.config.Anthropic", no_anthropic)
    assert get_client() is sentinel


def test_login_persists_selection_and_preserves_settings(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_file.write_text(_API_CONFIG)
    cfg = Config()
    cfg.set_session_provider("gateway")
    cfg.set_session_model("session-model")
    monkeypatch.setattr(auth, "config", cfg)

    def login(notify: Callable[[str, str], None]) -> object:
        notify("https://auth.openai.com/codex/device", "ABCD-EFGH")
        return object()

    monkeypatch.setattr(oauth, "login", login)
    auth.prompt_login()
    assert cfg.get_provider().id == "chatgpt"
    assert cfg.get_model() == "gpt-5.4"
    assert Config().get_provider().id == "chatgpt"
    assert Config().get_model() == "gpt-5.4"
    saved = tomllib.loads(config_file.read_text())
    assert saved["reasoning_effort"] == "low"
    assert "gateway" in saved["providers"]
    output = capsys.readouterr().out
    assert "https://auth.openai.com/codex/device" in output
    assert "ABCD-EFGH" in output


@pytest.mark.parametrize(
    "error", [KeyboardInterrupt(), EOFError(), ValueError("secret-token")]
)
def test_failed_login_preserves_disk_and_session_selection(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: BaseException,
) -> None:
    config_file.write_text(_API_CONFIG)
    cfg = Config()
    cfg.set_session_model("session-model")
    monkeypatch.setattr(auth, "config", cfg)

    def login(notify: Callable[[str, str], None]) -> None:
        raise error

    monkeypatch.setattr(oauth, "login", login)
    auth.prompt_login()
    assert config_file.read_text() == _API_CONFIG
    assert cfg.get_provider().id == "gateway"
    assert cfg.get_model() == "session-model"
    assert "secret-token" not in capsys.readouterr().out


@pytest.mark.parametrize("command", ["/login", "/logout"])
def test_auth_cli_works_without_provider(
    command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli, "prompt_login", lambda: calls.append("/login"))
    monkeypatch.setattr(cli, "prompt_logout", lambda: calls.append("/logout"))
    monkeypatch.setattr(cli, "config", Config())
    monkeypatch.setattr("sys.argv", ["mini", command])
    cli.main()
    assert calls == [command]
    assert command in COMMANDS


def test_logout_only_calls_local_oauth_and_preserves_selection(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file.write_text('provider = "chatgpt"\nmodel_id = "gpt-5.4"\n')
    before = config_file.read_text()
    calls: list[bool] = []
    monkeypatch.setattr(oauth, "logout", lambda: calls.append(True))
    auth.prompt_logout()
    assert calls == [True]
    assert config_file.read_text() == before


def test_chatgpt_model_list_never_requests_anthropic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = Config()
    cfg.set_session_provider("chatgpt")
    monkeypatch.setattr(models, "config", cfg)

    def unexpected() -> None:
        pytest.fail("ChatGPT model list must not request an API client")

    monkeypatch.setattr(models, "get_client", unexpected)
    assert models.fetch_models() == ["gpt-5.4"]


def test_chatgpt_model_picker_supports_manual_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        models, "select_from_list", lambda *args, **kwargs: "Enter model ID manually..."
    )
    monkeypatch.setattr("builtins.input", lambda _: " account-model ")
    assert models.select_model(["gpt-5.4"]) == "account-model"


def test_provider_picker_can_select_builtin(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file.write_text(_API_CONFIG)
    cfg = Config()
    monkeypatch.setattr(providers, "config", cfg)
    monkeypatch.setattr(
        providers, "select_from_list", lambda items, *args, **kwargs: items[-1]
    )
    providers.prompt_provider()
    assert Config().get_provider().id == "chatgpt"
    assert Config().get_model() == "existing-model"


def test_login_shows_safe_oauth_error(
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_file.write_text(_API_CONFIG)
    monkeypatch.setattr(auth, "config", Config())

    def login(notify: Callable[[str, str], None]) -> None:
        raise oauth.OAuthError("Device authorization expired. Run /login again.")

    monkeypatch.setattr(oauth, "login", login)
    auth.prompt_login()
    assert "Device authorization expired" in capsys.readouterr().out
    assert config_file.read_text() == _API_CONFIG
