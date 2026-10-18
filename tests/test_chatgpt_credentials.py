import json
import stat
import time
from pathlib import Path

import pytest

from mini_agent.chatgpt import credentials
from mini_agent.chatgpt.credentials import (
    ChatGPTAuthError,
    CredentialRecord,
    clear_credentials,
    get_access_token,
    host_id,
    load_credentials,
    save_credentials,
)
from mini_agent.chatgpt.http import HttpError


@pytest.fixture(autouse=True)
def credential_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(credentials, "CREDENTIALS_FILE", tmp_path / "chatgpt.json")
    monkeypatch.setattr(
        credentials, "REGISTRATION_FILE", tmp_path / "chatgpt-registration.json"
    )
    monkeypatch.setattr(credentials, "HOST_FILE", tmp_path / "chatgpt-host.json")
    monkeypatch.setattr(credentials, "LOCK_FILE", tmp_path / "chatgpt.lock")


def record(seconds: float = 3600) -> CredentialRecord:
    return CredentialRecord(
        client_id="oaiapp_test",
        access_token="access",
        refresh_token="refresh",
        expires_at=time.time() + seconds,
        scopes=["openid", "chatgpt.tokens.use.direct"],
        subject="subject",
        email="user@example.com",
    )


def test_save_and_load_private_record() -> None:
    value = record()
    save_credentials(value)

    loaded = load_credentials()
    assert loaded == value
    mode = stat.S_IMODE(credentials.CREDENTIALS_FILE.stat().st_mode)
    assert mode == 0o600


def test_clear_credentials_keeps_host_id() -> None:
    save_credentials(record())
    value = host_id()

    clear_credentials()

    assert load_credentials() is None
    assert host_id() == value


def test_host_id_is_stable() -> None:
    first = host_id()
    second = host_id()

    assert first == second
    assert first.startswith("urn:uuid:")


def test_not_logged_in_raises() -> None:
    with pytest.raises(ChatGPTAuthError, match="/login"):
        get_access_token()


def test_expired_token_is_refreshed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_credentials(record(seconds=-10))
    calls: list[dict[str, str]] = []

    def fake_post(url: str, data: dict[str, str], timeout: float = 30.0) -> dict:
        calls.append(data)
        return {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
            "scope": "openid chatgpt.tokens.use.direct",
        }

    monkeypatch.setattr(credentials, "post_form", fake_post)

    assert get_access_token() == "new-access"
    saved = load_credentials()
    assert saved is not None
    assert saved.access_token == "new-access"
    assert saved.refresh_token == "new-refresh"
    assert calls[0]["grant_type"] == "refresh_token"
    assert calls[0]["client_id"] == "oaiapp_test"


def test_invalid_refresh_clears_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_credentials(record(seconds=-10))

    def fake_post(url: str, data: dict[str, str], timeout: float = 30.0) -> dict:
        raise HttpError(400, json.dumps({"error": "invalid_grant"}).encode())

    monkeypatch.setattr(credentials, "post_form", fake_post)

    with pytest.raises(ChatGPTAuthError, match="/login"):
        get_access_token()

    assert load_credentials() is None
