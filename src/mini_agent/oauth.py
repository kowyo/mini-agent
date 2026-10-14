"""ChatGPT subscription login using the Codex device authorization protocol.

Credentials belong to mini-agent, never to the shared Codex credential store.
The protocol follows agent-foundation's CodexDeviceAuthorizationFlow.
"""

import base64
import json
import math
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from . import config as config_module

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTH_URL = "https://auth.openai.com"
VERIFICATION_URI = f"{AUTH_URL}/codex/device"
TOKEN_URL = f"{AUTH_URL}/oauth/token"


class OAuthError(ValueError):
    """An actionable error that never includes credentials or response bodies."""


@dataclass(frozen=True)
class Credentials:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    account_id: str
    expires_at: float


def _path() -> Path:
    return config_module.CONFIG_DIR / "chatgpt-auth.json"


def _string(document: dict, name: str) -> str:
    value = document.get(name)
    if not isinstance(value, str) or not value.strip():
        raise OAuthError(f"ChatGPT returned an invalid {name}; run /login again.")
    return value


def _payload(token: str) -> dict:
    """Read metadata from a token received over HTTPS, not verify a JWT."""
    try:
        payload = token.split(".")[1]
        value = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
        return value if isinstance(value, dict) else {}
    except IndexError, ValueError, UnicodeError:
        return {}


def _credentials(document: dict, previous: Credentials | None = None) -> Credentials:
    access_token = _string(document, "access_token")
    refresh_token = document.get("refresh_token")
    if refresh_token is None and previous is not None:
        refresh_token = previous.refresh_token
    refresh_token = _string({"refresh_token": refresh_token}, "refresh_token")
    account_id = document.get("account_id")
    for token in (document.get("id_token"), access_token):
        if account_id:
            break
        if isinstance(token, str):
            payload = _payload(token)
            claims = payload.get("https://api.openai.com/auth", {})
            if isinstance(claims, dict):
                account_id = claims.get("chatgpt_account_id")
            if not account_id:
                account_id = payload.get("chatgpt_account_id") or payload.get(
                    "account_id"
                )
    if not account_id and previous is not None:
        account_id = previous.account_id
    account_id = _string({"account_id": account_id}, "account_id")
    expires_in = document.get("expires_in")
    if isinstance(expires_in, (int, float)) and not isinstance(expires_in, bool):
        expires_at = time.time() + expires_in
    else:
        expires_at = _payload(access_token).get("exp")
    if (
        not isinstance(expires_at, (int, float))
        or isinstance(expires_at, bool)
        or not math.isfinite(expires_at)
        or expires_at <= time.time()
    ):
        raise OAuthError("ChatGPT returned an invalid token expiry; run /login again.")
    return Credentials(access_token, refresh_token, account_id, float(expires_at))


def _post(
    client: httpx.Client,
    url: str,
    *,
    data: dict[str, str] | None = None,
    json: dict[str, str] | None = None,
    timeout: float = 30,
) -> httpx.Response:
    try:
        return client.post(url, data=data, json=json, timeout=timeout)
    except httpx.HTTPError:
        raise OAuthError("Could not reach ChatGPT authentication; try again.") from None


def _document(response: httpx.Response) -> dict:
    if response.status_code != 200:
        raise OAuthError(
            f"ChatGPT authentication failed (HTTP {response.status_code}); run /login again."
        )
    try:
        document = response.json()
    except ValueError:
        raise OAuthError(
            "ChatGPT returned an invalid authentication response."
        ) from None
    if not isinstance(document, dict):
        raise OAuthError("ChatGPT returned an invalid authentication response.")
    return document


@contextmanager
def _locked() -> Iterator[None]:
    """Serialize refresh-token rotation across mini-agent processes."""
    path = _path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    deadline = time.monotonic() + 30
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise OAuthError(
                    "ChatGPT credentials are locked by another process. "
                    "If no mini-agent is running, remove chatgpt-auth.lock and retry."
                ) from None
            time.sleep(0.1)
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def _save(credentials: Credentials) -> None:
    path = _path()
    fd, name = tempfile.mkstemp(prefix=".chatgpt-auth-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(asdict(credentials), file)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _load() -> Credentials:
    try:
        document = json.loads(_path().read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError
        expires_at = document["expires_at"]
        if (
            not isinstance(expires_at, (int, float))
            or isinstance(expires_at, bool)
            or not math.isfinite(expires_at)
        ):
            raise ValueError
        return Credentials(
            _string(document, "access_token"),
            _string(document, "refresh_token"),
            _string(document, "account_id"),
            float(expires_at),
        )
    except FileNotFoundError:
        raise OAuthError("ChatGPT is not logged in. Run /login first.") from None
    except ValueError, KeyError, TypeError:
        raise OAuthError("ChatGPT credentials are invalid. Run /login again.") from None


def get_credentials() -> Credentials:
    with _locked():
        credentials = _load()
        if credentials.expires_at > time.time() + 60:
            return credentials
        with httpx.Client(timeout=30) as client:
            document = _document(
                _post(
                    client,
                    TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "client_id": CLIENT_ID,
                        "refresh_token": credentials.refresh_token,
                    },
                )
            )
        credentials = _credentials(document, credentials)
        _save(credentials)
        return credentials


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise OAuthError("ChatGPT login expired. Run /login to try again.")
    return remaining


def login(notify: Callable[[str, str], None]) -> Credentials:
    """Show a browser verification URL/code and poll for fifteen minutes."""
    with httpx.Client(timeout=30) as client:
        response = _post(
            client,
            f"{AUTH_URL}/api/accounts/deviceauth/usercode",
            json={"client_id": CLIENT_ID},
        )
        if response.status_code == 404:
            raise OAuthError("ChatGPT device login is unavailable for this account.")
        document = _document(response)
        device_auth_id = _string(document, "device_auth_id")
        user_code = _string(document, "user_code")
        if not all(c.isascii() and (c.isalnum() or c == "-") for c in user_code):
            raise OAuthError("ChatGPT returned an invalid device code.")
        interval = document.get("interval", 5)
        if isinstance(interval, str) and interval.isascii() and interval.isdecimal():
            interval = int(interval)
        if not isinstance(interval, int) or isinstance(interval, bool) or interval <= 0:
            raise OAuthError("ChatGPT returned an invalid polling interval.")
        deadline = time.monotonic() + 900
        notify(VERIFICATION_URI, user_code)
        while True:
            time.sleep(min(interval, _remaining(deadline)))
            remaining = _remaining(deadline)
            response = _post(
                client,
                f"{AUTH_URL}/api/accounts/deviceauth/token",
                json={"device_auth_id": device_auth_id, "user_code": user_code},
                timeout=min(30, remaining),
            )
            if response.status_code in {403, 404}:
                continue
            document = _document(response)
            document = _document(
                _post(
                    client,
                    TOKEN_URL,
                    data={
                        "grant_type": "authorization_code",
                        "client_id": CLIENT_ID,
                        "code": _string(document, "authorization_code"),
                        "code_verifier": _string(document, "code_verifier"),
                        "redirect_uri": f"{AUTH_URL}/deviceauth/callback",
                    },
                    timeout=min(30, _remaining(deadline)),
                )
            )
            credentials = _credentials(document)
            with _locked():
                _remaining(deadline)
                _save(credentials)
            return credentials


def logout() -> None:
    """Remove only mini-agent's local credentials; remote sessions are unchanged."""
    with _locked():
        _path().unlink(missing_ok=True)
