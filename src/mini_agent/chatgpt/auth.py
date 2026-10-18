import base64
import hashlib
import hmac
import html
import secrets
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer

import jwt

from .credentials import (
    ISSUER,
    RESOURCE,
    SCOPES,
    ChatGPTAuthError,
    CredentialRecord,
    clear_credentials,
    get_account_label,
    host_id,
    is_logged_in,
    load_credentials,
    load_registration,
    save_credentials,
    save_registration,
)
from .http import HttpError, get_json, post_form

DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
CALLBACK_PATH = "/auth/callback"
LOGIN_TIMEOUT = 300.0


@dataclass
class _Discovery:
    authorization_endpoint: str
    token_endpoint: str
    revocation_endpoint: str | None
    jwks_uri: str


@dataclass
class _Callback:
    code: str | None = None
    state: str | None = None
    client_id: str | None = None
    error: str | None = None


def discover() -> _Discovery:
    try:
        data = get_json(DISCOVERY_URL)
    except (OSError, HttpError) as error:
        raise ChatGPTAuthError("Could not reach ChatGPT sign-in.") from error
    if data.get("issuer") != ISSUER:
        raise ChatGPTAuthError("ChatGPT sign-in configuration could not be verified.")
    values: dict[str, str] = {}
    for key in (
        "authorization_endpoint",
        "token_endpoint",
        "jwks_uri",
        "revocation_endpoint",
    ):
        value = data.get(key)
        if key == "revocation_endpoint" and value is None:
            continue
        if (
            not isinstance(value, str)
            or urllib.parse.urlparse(value).netloc
            != urllib.parse.urlparse(ISSUER).netloc
        ):
            raise ChatGPTAuthError(
                "ChatGPT sign-in configuration could not be verified."
            )
        values[key] = value
    return _Discovery(
        authorization_endpoint=values["authorization_endpoint"],
        token_endpoint=values["token_endpoint"],
        revocation_endpoint=values.get("revocation_endpoint"),
        jwks_uri=values["jwks_uri"],
    )


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def _authorization_url(
    endpoint: str,
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    nonce: str,
    challenge: str,
    host_id_value: str,
    existing: CredentialRecord | None,
) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "ext_agent_host_id": host_id_value,
    }
    if existing is None:
        params["agent_name_hint"] = "mini-agent"
    elif existing.email:
        params["login_hint"] = existing.email
    return f"{endpoint}?{urllib.parse.urlencode(params)}"


def verify_id_token(
    id_token: str,
    client_id: str,
    nonce: str | None = None,
) -> dict[str, object]:
    discovery = discover()
    try:
        key = jwt.PyJWKClient(discovery.jwks_uri, timeout=15).get_signing_key_from_jwt(
            id_token
        )
        payload = jwt.decode(
            id_token,
            key.key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub"]},
        )
    except (jwt.PyJWTError, OSError) as error:
        raise ChatGPTAuthError(
            "The ChatGPT identity could not be verified. Sign in again."
        ) from error
    if not isinstance(payload, dict) or not isinstance(payload.get("sub"), str):
        raise ChatGPTAuthError("ChatGPT did not return a verifiable identity.")
    if nonce is not None and payload.get("nonce") != nonce:
        raise ChatGPTAuthError("ChatGPT identity verification failed.")
    if payload.get("azp") is not None and payload["azp"] != client_id:
        raise ChatGPTAuthError("ChatGPT identity verification failed.")
    return payload


def _callback_handler(
    callback: _Callback,
    finished: threading.Event,
    expected_state: str,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != CALLBACK_PATH:
                self.send_response(404)
                self.end_headers()
                return
            query = urllib.parse.parse_qs(parsed.query)
            state = query.get("state", [""])[0]
            if not hmac.compare_digest(state, expected_state):
                self.send_response(400)
                self.end_headers()
                self.wfile.write(
                    b"Invalid sign-in state. Return to the browser tab that started sign-in."
                )
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>ChatGPT sign-in complete</h1>"
                b"<p>You can close this tab and return to mini-agent.</p></body></html>"
            )
            callback.state = state
            callback.code = query.get("code", [None])[0]
            callback.client_id = query.get("client_id", [None])[0]
            callback.error = query.get("error", [None])[0]
            finished.set()

        def log_message(self, format: str, *args: object) -> None:
            pass

    return Handler


def login() -> CredentialRecord:
    existing = load_credentials() or load_registration()
    discovery = discover()
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    callback = _Callback()
    finished = threading.Event()
    try:
        server = HTTPServer(
            ("127.0.0.1", 0),
            _callback_handler(callback, finished, state),
        )
    except OSError as error:
        raise ChatGPTAuthError(
            "Could not start the local ChatGPT sign-in listener."
        ) from error
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}{CALLBACK_PATH}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client_id = (
            existing.client_id if existing is not None else "dynamic_agent_client"
        )
        url = _authorization_url(
            discovery.authorization_endpoint,
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            nonce=nonce,
            challenge=challenge,
            host_id_value=host_id(),
            existing=existing,
        )
        if not webbrowser.open(url):
            raise ChatGPTAuthError("Could not open the browser for ChatGPT sign-in.")
        if not finished.wait(LOGIN_TIMEOUT):
            raise ChatGPTAuthError(
                "ChatGPT sign-in timed out. Run /login to try again."
            )
        if callback.error:
            raise ChatGPTAuthError(
                f"ChatGPT sign-in was not completed ({html.escape(callback.error)})."
            )
        if not callback.code:
            raise ChatGPTAuthError(
                "ChatGPT sign-in did not return an authorization code."
            )
        issued_client_id = callback.client_id or (
            existing.client_id if existing is not None else None
        )
        if issued_client_id is None or issued_client_id == "dynamic_agent_client":
            raise ChatGPTAuthError("ChatGPT did not complete app registration.")
        try:
            data = post_form(
                discovery.token_endpoint,
                {
                    "grant_type": "authorization_code",
                    "client_id": issued_client_id,
                    "code": callback.code,
                    "code_verifier": verifier,
                    "redirect_uri": redirect_uri,
                    "resource": RESOURCE,
                },
            )
        except HttpError as error:
            raise ChatGPTAuthError(
                f"ChatGPT rejected the sign-in ({error.status}). Run /login to try again."
            ) from error
        id_token = data.get("id_token")
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        expires_in = data.get("expires_in")
        scope = data.get("scope")
        if not isinstance(id_token, str) or not id_token:
            raise ChatGPTAuthError("ChatGPT returned incomplete credentials.")
        if not isinstance(access_token, str) or not access_token:
            raise ChatGPTAuthError("ChatGPT returned incomplete credentials.")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise ChatGPTAuthError("ChatGPT returned incomplete credentials.")
        if not isinstance(expires_in, int | float) or expires_in <= 0:
            raise ChatGPTAuthError("ChatGPT returned incomplete credentials.")
        if not isinstance(scope, str):
            raise ChatGPTAuthError("ChatGPT did not confirm granted permissions.")
        payload = verify_id_token(id_token, issued_client_id, nonce)
        scopes = scope.split()
        if "chatgpt.tokens.use.direct" not in scopes:
            raise ChatGPTAuthError(
                "ChatGPT plan usage was not authorized. Run /login and allow "
                "mini-agent to use your ChatGPT plan."
            )
        record = CredentialRecord(
            client_id=issued_client_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=time.time() + float(expires_in),
            scopes=scopes,
            subject=str(payload["sub"]),
            email=str(payload["email"]) if payload.get("email") else None,
            id_token=id_token,
            host_id=host_id(),
        )
        save_credentials(record)
        save_registration(record)
        return record
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def logout() -> str | None:
    try:
        record = load_credentials()
    except ChatGPTAuthError:
        clear_credentials()
        return "Saved ChatGPT credentials were invalid and have been removed."
    if record is None:
        clear_credentials()
        return None
    save_registration(record)
    warning: str | None = None
    try:
        discovery = discover()
        if discovery.revocation_endpoint:
            post_form(
                discovery.revocation_endpoint,
                {
                    "token": record.refresh_token,
                    "token_type_hint": "refresh_token",
                    "client_id": record.client_id,
                },
            )
        else:
            warning = (
                "Remote revocation is unavailable; local credentials were removed."
            )
    except OSError, HttpError, ChatGPTAuthError:
        warning = (
            "Local credentials were removed, but remote revocation could not be "
            "confirmed. You can disconnect mini-agent in ChatGPT settings."
        )
    clear_credentials()
    return warning


__all__ = [
    "ChatGPTAuthError",
    "get_account_label",
    "is_logged_in",
    "login",
    "logout",
]
