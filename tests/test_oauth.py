import base64
import json
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from mini_agent import oauth


def token(account: str = "account-1", expiry: float = 5000) -> str:
    payload = json.dumps(
        {"exp": expiry, "https://api.openai.com/auth": {"chatgpt_account_id": account}}
    ).encode()
    return "header." + base64.urlsafe_b64encode(payload).decode().rstrip("=") + ".sig"


def install_client(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(oauth.httpx, "Client", lambda **kwargs: client)
    monkeypatch.setattr(oauth.time, "time", lambda: 1000)


def test_device_login_poll_exchange_and_private_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    requests: list[httpx.Request] = []
    polls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal polls
        requests.append(request)
        if request.url.path.endswith("usercode"):
            assert json.loads(request.content) == {"client_id": oauth.CLIENT_ID}
            return httpx.Response(
                200,
                json={
                    "device_auth_id": "device",
                    "user_code": "AB-CD",
                    "interval": "1",
                },
            )
        if request.url.path.endswith("deviceauth/token"):
            polls += 1
            assert json.loads(request.content) == {
                "device_auth_id": "device",
                "user_code": "AB-CD",
            }
            if polls == 1:
                return httpx.Response(403)
            if polls == 2:
                return httpx.Response(404)
            return httpx.Response(
                200, json={"authorization_code": "code", "code_verifier": "verifier"}
            )
        assert parse_qs(request.content.decode()) == {
            "grant_type": ["authorization_code"],
            "client_id": [oauth.CLIENT_ID],
            "code": ["code"],
            "code_verifier": ["verifier"],
            "redirect_uri": ["https://auth.openai.com/deviceauth/callback"],
        }
        return httpx.Response(
            200,
            json={
                "access_token": token(),
                "refresh_token": "refresh",
                "expires_in": 3600,
            },
        )

    install_client(monkeypatch, handler)
    monkeypatch.setattr(oauth.time, "sleep", lambda seconds: None)
    notices: list[tuple[str, str]] = []
    credentials = oauth.login(lambda uri, code: notices.append((uri, code)))
    assert notices == [(oauth.VERIFICATION_URI, "AB-CD")]
    assert credentials.account_id == "account-1"
    assert credentials.expires_at == 4600
    assert oauth.get_credentials() == credentials
    path = tmp_path / "chatgpt-auth.json"
    assert json.loads(path.read_text())["refresh_token"] == "refresh"
    if oauth.os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".chatgpt-auth-*"))
    assert not (tmp_path / "chatgpt-auth.lock").exists()
    assert "refresh" not in repr(credentials)


def test_refresh_rotates_and_preserves_account(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with oauth._locked():
        oauth._save(oauth.Credentials("old", "refresh", "account-1", 1001))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == oauth.TOKEN_URL
        assert parse_qs(request.content.decode())["refresh_token"] == ["refresh"]
        return httpx.Response(
            200,
            json={
                "access_token": "new",
                "refresh_token": "rotated",
                "expires_in": 3600,
            },
        )

    install_client(monkeypatch, handler)
    credentials = oauth.get_credentials()
    assert credentials == oauth.Credentials("new", "rotated", "account-1", 4600)
    assert oauth.get_credentials() == credentials
    assert (
        json.loads((tmp_path / "chatgpt-auth.json").read_text())["refresh_token"]
        == "rotated"
    )


def test_refresh_without_new_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oauth.time, "time", lambda: 1000)
    previous = oauth.Credentials("old", "refresh", "account-1", 1001)
    assert (
        oauth._credentials(
            {"access_token": "new", "expires_in": 3600}, previous
        ).refresh_token
        == "refresh"
    )


def test_refresh_failure_keeps_store_and_redacts_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with oauth._locked():
        oauth._save(oauth.Credentials("old", "refresh", "account-1", 1001))
    before = (tmp_path / "chatgpt-auth.json").read_bytes()
    install_client(
        monkeypatch, lambda request: httpx.Response(401, text="secret-token")
    )
    with pytest.raises(oauth.OAuthError, match="HTTP 401") as error:
        oauth.get_credentials()
    assert "secret-token" not in str(error.value)
    assert (tmp_path / "chatgpt-auth.json").read_bytes() == before
    assert not (tmp_path / "chatgpt-auth.lock").exists()


def test_expired_device_login_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    install_client(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"device_auth_id": "id", "user_code": "CODE", "interval": 9999}
        ),
    )
    elapsed = 0.0

    def sleep(seconds: float) -> None:
        nonlocal elapsed
        elapsed += seconds

    monkeypatch.setattr(oauth.time, "monotonic", lambda: elapsed)
    monkeypatch.setattr(oauth.time, "sleep", sleep)
    with pytest.raises(oauth.OAuthError, match="expired"):
        oauth.login(lambda uri, code: None)
    assert elapsed == 900


@pytest.mark.parametrize(
    "document",
    [
        [],
        {},
        {"device_auth_id": "id", "user_code": "<unsafe>"},
        {"device_auth_id": "id", "user_code": "CODE", "interval": True},
    ],
)
def test_malformed_login_rejected(
    monkeypatch: pytest.MonkeyPatch, document: object
) -> None:
    install_client(monkeypatch, lambda request: httpx.Response(200, json=document))
    with pytest.raises(oauth.OAuthError):
        oauth.login(lambda uri, code: None)


def test_interrupt_does_not_replace_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with oauth._locked():
        oauth._save(oauth.Credentials("old", "refresh", "account-1", 9999))
    before = (tmp_path / "chatgpt-auth.json").read_bytes()
    install_client(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"device_auth_id": "id", "user_code": "CODE"}
        ),
    )

    def notify(uri: str, code: str) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        oauth.login(notify)
    assert (tmp_path / "chatgpt-auth.json").read_bytes() == before


def test_missing_corrupt_and_logout(tmp_path: Path) -> None:
    with pytest.raises(oauth.OAuthError, match="not logged in"):
        oauth.get_credentials()
    path = tmp_path / "chatgpt-auth.json"
    path.write_text("not json")
    with pytest.raises(oauth.OAuthError, match="invalid"):
        oauth.get_credentials()
    other = tmp_path / "auth.json"
    other.write_text("unrelated")
    oauth.logout()
    oauth.logout()
    assert not path.exists()
    assert other.read_text() == "unrelated"


def test_oversized_stored_expiry_is_invalid(tmp_path: Path) -> None:
    path = tmp_path / "chatgpt-auth.json"
    path.write_text(
        json.dumps(
            {
                "access_token": "secret",
                "refresh_token": "refresh",
                "account_id": "account",
                "expires_at": 10**400,
            }
        )
    )
    before = path.read_bytes()
    with pytest.raises(oauth.OAuthError, match="credentials are invalid") as error:
        oauth.get_credentials()
    assert "secret" not in str(error.value)
    assert path.read_bytes() == before
    assert not (tmp_path / "chatgpt-auth.lock").exists()


@pytest.mark.parametrize("expiry", [None, True, float("nan"), -1, 0])
def test_invalid_expiry(monkeypatch: pytest.MonkeyPatch, expiry: object) -> None:
    monkeypatch.setattr(oauth.time, "time", lambda: 1000)
    with pytest.raises(oauth.OAuthError, match="expiry"):
        oauth._credentials(
            {
                "access_token": "opaque",
                "refresh_token": "r",
                "account_id": "a",
                "expires_in": expiry,
            }
        )


def test_network_error_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret", request=request)

    install_client(monkeypatch, handler)
    with pytest.raises(oauth.OAuthError, match="Could not reach") as error:
        oauth.login(lambda uri, code: None)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "claims",
    [
        {"https://api.openai.com/auth": {"chatgpt_account_id": "account"}},
        {"chatgpt_account_id": "account"},
        {"account_id": "account"},
    ],
)
def test_id_token_account_claims(monkeypatch: pytest.MonkeyPatch, claims: dict) -> None:
    monkeypatch.setattr(oauth.time, "time", lambda: 1000)
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    credentials = oauth._credentials(
        {
            "access_token": "opaque",
            "id_token": f"header.{encoded}.signature",
            "refresh_token": "refresh",
            "expires_in": 3600,
        }
    )
    assert credentials.account_id == "account"


@pytest.mark.parametrize("expire_at", ["poll", "exchange"])
def test_login_deadline_preserves_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, expire_at: str
) -> None:
    with oauth._locked():
        oauth._save(oauth.Credentials("old", "refresh", "account", 9000))
    before = (tmp_path / "chatgpt-auth.json").read_bytes()
    elapsed = 0.0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal elapsed
        if request.url.path.endswith("usercode"):
            return httpx.Response(
                200, json={"device_auth_id": "id", "user_code": "CODE"}
            )
        if request.url.path.endswith("deviceauth/token"):
            if expire_at == "poll":
                elapsed = 901
            return httpx.Response(
                200, json={"authorization_code": "code", "code_verifier": "verifier"}
            )
        elapsed = 901
        return httpx.Response(
            200,
            json={"access_token": token(), "refresh_token": "new", "expires_in": 3600},
        )

    install_client(monkeypatch, handler)
    monkeypatch.setattr(oauth.time, "monotonic", lambda: elapsed)
    monkeypatch.setattr(oauth.time, "sleep", lambda seconds: None)
    with pytest.raises(oauth.OAuthError, match="expired"):
        oauth.login(lambda uri, code: None)
    assert (tmp_path / "chatgpt-auth.json").read_bytes() == before


def test_lock_timeout_and_interrupt_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(KeyboardInterrupt), oauth._locked():
        raise KeyboardInterrupt
    lock = tmp_path / "chatgpt-auth.lock"
    assert not lock.exists()
    lock.write_text("")
    clock = iter([0, 31])
    monkeypatch.setattr(oauth.time, "monotonic", lambda: next(clock))
    with pytest.raises(oauth.OAuthError, match="locked"), oauth._locked():
        pytest.fail("Must not acquire an existing lock")
    assert lock.exists()


def test_atomic_write_failure_keeps_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with oauth._locked():
        oauth._save(oauth.Credentials("old", "refresh", "account", 9000))
    before = (tmp_path / "chatgpt-auth.json").read_bytes()

    def fail(fd: int) -> None:
        raise OSError("disk failure")

    monkeypatch.setattr(oauth.os, "fsync", fail)
    with pytest.raises(OSError, match="disk failure"), oauth._locked():
        oauth._save(oauth.Credentials("new", "rotated", "account", 9000))
    assert (tmp_path / "chatgpt-auth.json").read_bytes() == before
    assert not list(tmp_path.glob(".chatgpt-auth-*"))
    assert not (tmp_path / "chatgpt-auth.lock").exists()


def test_overlapping_refresh_callers_rotate_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    with oauth._locked():
        oauth._save(oauth.Credentials("old", "refresh", "account", 1001))
    entered = Event()
    contended = Event()
    release = Event()
    calls = []
    original_open = oauth.os.open

    def observed_open(
        path: str | os.PathLike[str], flags: int, mode: int = 0o777
    ) -> int:
        try:
            return original_open(path, flags, mode)
        except FileExistsError:
            # Signal only after the second caller actually encounters the lock.
            contended.set()
            raise

    monkeypatch.setattr(oauth.os, "open", observed_open)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        entered.set()
        assert release.wait(timeout=5)
        return httpx.Response(
            200,
            json={
                "access_token": "new",
                "refresh_token": "rotated",
                "expires_in": 3600,
            },
        )

    install_client(monkeypatch, handler)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(oauth.get_credentials)
        try:
            assert entered.wait(timeout=5)
            second = pool.submit(oauth.get_credentials)
            assert contended.wait(timeout=5)
            assert len(calls) == 1
        finally:
            release.set()
        assert first.result(timeout=5) == second.result(timeout=5)
    assert len(calls) == 1
