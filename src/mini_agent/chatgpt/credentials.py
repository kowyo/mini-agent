import contextlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from ..config import CONFIG_DIR
from .http import HttpError, post_form

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
TOKEN_ENDPOINT = f"{ISSUER}/api/accounts/oauth/token"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"

CREDENTIALS_FILE = CONFIG_DIR / "chatgpt.json"
REGISTRATION_FILE = CONFIG_DIR / "chatgpt-registration.json"
HOST_FILE = CONFIG_DIR / "chatgpt-host.json"
LOCK_FILE = CONFIG_DIR / "chatgpt.lock"

_REFRESH_ERRORS = {
    "invalid_grant",
    "invalid_refresh_token",
    "token_expired",
    "refresh_token_expired",
    "refresh_token_invalidated",
    "refresh_token_reused",
}


class ChatGPTAuthError(Exception):
    pass


@dataclass
class CredentialRecord:
    client_id: str
    access_token: str
    refresh_token: str
    expires_at: float
    scopes: list[str]
    subject: str
    email: str | None = None
    id_token: str | None = None
    host_id: str | None = None

    @property
    def has_plan_usage(self) -> bool:
        return "chatgpt.tokens.use.direct" in self.scopes

    @property
    def label(self) -> str:
        return self.email or self.subject or self.client_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "scopes": self.scopes,
            "subject": self.subject,
            "email": self.email,
            "id_token": self.id_token,
            "host_id": self.host_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CredentialRecord:
        try:
            scopes = data["scopes"]
            if not isinstance(scopes, list):
                raise ValueError
            return cls(
                client_id=str(data["client_id"]),
                access_token=str(data["access_token"]),
                refresh_token=str(data["refresh_token"]),
                expires_at=float(data["expires_at"]),
                scopes=[str(scope) for scope in scopes],
                subject=str(data["subject"]),
                email=str(data["email"]) if data.get("email") else None,
                id_token=str(data["id_token"]) if data.get("id_token") else None,
                host_id=str(data["host_id"]) if data.get("host_id") else None,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ChatGPTAuthError("Saved ChatGPT credentials are invalid.") from error


def _write_private(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.parent.chmod(0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as file:
            json.dump(data, file, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
        with contextlib.suppress(OSError):
            path.chmod(0o600)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def load_credentials() -> CredentialRecord | None:
    try:
        data = json.loads(CREDENTIALS_FILE.read_text())
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as error:
        raise ChatGPTAuthError(
            "Saved ChatGPT credentials could not be read."
        ) from error
    if not isinstance(data, dict):
        raise ChatGPTAuthError("Saved ChatGPT credentials are invalid.")
    if data.get("client_id") == "dynamic_agent_client":
        raise ChatGPTAuthError("Saved ChatGPT credentials are invalid.")
    return CredentialRecord.from_dict(data)


def save_credentials(record: CredentialRecord) -> None:
    _write_private(CREDENTIALS_FILE, record.to_dict())


def save_registration(record: CredentialRecord) -> None:
    _write_private(
        REGISTRATION_FILE,
        {
            "client_id": record.client_id,
            "subject": record.subject,
            "email": record.email,
            "host_id": record.host_id,
        },
    )


def load_registration() -> CredentialRecord | None:
    try:
        data = json.loads(REGISTRATION_FILE.read_text())
    except FileNotFoundError:
        return None
    except OSError, json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("client_id"), str):
        return None
    client_id = data["client_id"]
    if client_id == "dynamic_agent_client":
        return None
    return CredentialRecord(
        client_id=client_id,
        access_token="",
        refresh_token="",
        expires_at=0,
        scopes=[],
        subject=str(data.get("subject", "")),
        email=str(data["email"]) if data.get("email") else None,
        host_id=str(data["host_id"]) if data.get("host_id") else None,
    )


def clear_credentials() -> None:
    with contextlib.suppress(FileNotFoundError):
        CREDENTIALS_FILE.unlink()


def host_id() -> str:
    try:
        data = json.loads(HOST_FILE.read_text())
        value = data.get("id")
        if isinstance(value, str) and value.startswith("urn:uuid:"):
            return value
    except FileNotFoundError, OSError, json.JSONDecodeError:
        pass
    value = f"urn:uuid:{uuid.uuid4()}"
    _write_private(HOST_FILE, {"version": 1, "id": value})
    return value


def _error_code(error: HttpError) -> str | None:
    try:
        body = json.loads(error.body)
    except json.JSONDecodeError, UnicodeDecodeError:
        return None
    if not isinstance(body, dict):
        return None
    value = body.get("error")
    if isinstance(value, str):
        return value
    if isinstance(body.get("error_reason"), str):
        return str(body["error_reason"])
    return None


def refresh_credentials(record: CredentialRecord) -> CredentialRecord:
    try:
        data = post_form(
            TOKEN_ENDPOINT,
            {
                "grant_type": "refresh_token",
                "client_id": record.client_id,
                "refresh_token": record.refresh_token,
                "resource": RESOURCE,
            },
        )
    except HttpError as error:
        code = _error_code(error)
        if code in _REFRESH_ERRORS:
            clear_credentials()
            raise ChatGPTAuthError(
                "Your ChatGPT session expired. Run /login to sign in again."
            ) from error
        raise ChatGPTAuthError(
            f"Could not refresh ChatGPT credentials: {code or error.status}"
        ) from error

    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    expires_in = data.get("expires_in")
    if not isinstance(access_token, str) or not access_token:
        raise ChatGPTAuthError("ChatGPT returned an invalid token response.")
    if not isinstance(refresh_token, str) or not refresh_token:
        refresh_token = record.refresh_token
    if not isinstance(expires_in, int | float) or expires_in <= 0:
        raise ChatGPTAuthError("ChatGPT returned an invalid token response.")

    scope = data.get("scope")
    scopes = (
        [str(value) for value in scope.split()]
        if isinstance(scope, str)
        else record.scopes
    )
    id_token = data.get("id_token")
    if isinstance(id_token, str) and id_token:
        from .auth import verify_id_token

        payload = verify_id_token(id_token, record.client_id)
        if payload.get("sub") != record.subject:
            raise ChatGPTAuthError(
                "The refreshed ChatGPT identity does not match this account. Run /login."
            )
        record.id_token = id_token
    record.access_token = access_token
    record.refresh_token = refresh_token
    record.expires_at = time.time() + float(expires_in)
    record.scopes = scopes
    save_credentials(record)
    return record


def get_access_token() -> str:
    record = load_credentials()
    if record is None:
        raise ChatGPTAuthError("Not signed in to ChatGPT. Run /login.")
    if time.time() < record.expires_at - 60:
        return record.access_token
    try:
        with FileLock(str(LOCK_FILE), timeout=30):
            record = load_credentials()
            if record is None:
                raise ChatGPTAuthError("Not signed in to ChatGPT. Run /login.")
            if time.time() >= record.expires_at - 60:
                record = refresh_credentials(record)
            return record.access_token
    except Timeout as error:
        raise ChatGPTAuthError(
            "Another process is refreshing ChatGPT credentials. Try again."
        ) from error


def is_logged_in() -> bool:
    try:
        record = load_credentials()
    except ChatGPTAuthError:
        return False
    return record is not None and record.has_plan_usage


def get_account_label() -> str | None:
    try:
        record = load_credentials()
    except ChatGPTAuthError:
        return None
    return record.label if record is not None else None
