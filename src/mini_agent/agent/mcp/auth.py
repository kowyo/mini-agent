import asyncio
import json
import logging
import threading
from collections.abc import AsyncGenerator
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import httpx2
from mcp.client.auth import OAuthClientProvider, OAuthFlowError
from mcp.shared.auth import (
    AuthorizationCodeResult,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)
from pydantic import AnyUrl

from ...config import CONFIG_DIR
from .config import HttpServerConfig

AUTH_DIR = CONFIG_DIR / "mcp-auth"
AUTHORIZATION_TIMEOUT = 300.0

logging.getLogger("mcp.client.auth.oauth2").setLevel(logging.CRITICAL)

GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
DEVICE_POLL_INTERVAL = 5.0

DEFAULT_CLIENT_IDS = {
    "api.githubcopilot.com": "Iv23liNOejv4Nb4755ff",
}

CALLBACK_PAGE = (
    "<html><body><p>mini-agent is authorized. You can close this tab.</p></body></html>"
)


def _prompt_authorization(server_name: str, instruction: str) -> None:
    print(f"mcp: {server_name}: authorization needed — {instruction}\n")


class AuthorizationRequiredError(Exception):
    """User interaction is needed to authorize; raised in non-interactive mode."""


class FileTokenStorage:
    """Persists OAuth tokens and client registration per server."""

    def __init__(self, server_name: str) -> None:
        self._path = AUTH_DIR / f"{server_name}.json"

    def _read(self) -> dict:
        if not self._path.is_file():
            return {}
        try:
            return json.loads(self._path.read_text())
        except OSError, json.JSONDecodeError:
            return {}

    def _write(self, data: dict) -> None:
        AUTH_DIR.mkdir(parents=True, exist_ok=True)
        self._path.touch(mode=0o600, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2))

    async def get_tokens(self) -> OAuthToken | None:
        tokens = self._read().get("tokens")
        return OAuthToken.model_validate(tokens) if tokens else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        data = self._read()
        data["tokens"] = tokens.model_dump(mode="json", exclude_none=True)
        self._write(data)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        info = self._read().get("client_info")
        return OAuthClientInformationFull.model_validate(info) if info else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        data = self._read()
        data["client_info"] = client_info.model_dump(mode="json", exclude_none=True)
        self._write(data)


class _PreRegisteredStorage(FileTokenStorage):
    """Serves a pre-registered OAuth client, skipping dynamic registration."""

    def __init__(
        self, server_name: str, client_info: OAuthClientInformationFull
    ) -> None:
        super().__init__(server_name)
        self._client_info = client_info

    async def get_client_info(self) -> OAuthClientInformationFull:
        return self._client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        pass


class _CallbackServer(HTTPServer):
    flow: OAuthBrowserFlow


class _CallbackHandler(BaseHTTPRequestHandler):
    server: _CallbackServer

    def do_GET(self) -> None:  # noqa: N802
        query = parse_qs(urlparse(self.path).query)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(CALLBACK_PAGE.encode())
        self.server.flow.receive(query)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


class OAuthBrowserFlow:
    """Loopback redirect target for the OAuth authorization-code flow."""

    def __init__(self, server_name: str, interactive: bool) -> None:
        self._server_name = server_name
        self._interactive = interactive
        self._server = _CallbackServer(("127.0.0.1", 0), _CallbackHandler)
        self._server.flow = self
        self._done = threading.Event()
        self._query: dict[str, list[str]] = {}
        self.redirect_uri = (
            f"http://127.0.0.1:{self._server.server_address[1]}/callback"
        )

    def receive(self, query: dict[str, list[str]]) -> None:
        self._query = query
        self._done.set()

    async def redirect_handler(self, authorization_url: str) -> None:
        if not self._interactive:
            raise AuthorizationRequiredError(self._server_name)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        _prompt_authorization(self._server_name, f"open {authorization_url}")

    async def callback_handler(self) -> AuthorizationCodeResult:
        try:
            done = await asyncio.to_thread(self._done.wait, AUTHORIZATION_TIMEOUT)
            if not done:
                raise OAuthFlowError("authorization timed out")
            if "error" in self._query:
                raise OAuthFlowError(f"authorization failed: {self._query['error'][0]}")
            if "code" not in self._query:
                raise OAuthFlowError("authorization callback carried no code")
            return AuthorizationCodeResult(
                code=self._query["code"][0],
                state=self._query.get("state", [None])[0],
                iss=self._query.get("iss", [None])[0],
            )
        finally:
            self._server.shutdown()
            self._server.server_close()


class GitHubDeviceAuth(httpx2.Auth):
    """GitHub device flow: public client_id only, no secret or callback."""

    def __init__(self, server_name: str, client_id: str, interactive: bool) -> None:
        self._server_name = server_name
        self._storage = FileTokenStorage(server_name)
        self._client_id = client_id
        self._interactive = interactive
        self._lock = asyncio.Lock()

    async def async_auth_flow(
        self, request: httpx2.Request
    ) -> AsyncGenerator[httpx2.Request, httpx2.Response]:
        tokens = await self._ensure_tokens()
        request.headers["Authorization"] = f"Bearer {tokens.access_token}"
        response = yield request
        if response.status_code == 401:
            tokens = await self._renew(tokens)
            request.headers["Authorization"] = f"Bearer {tokens.access_token}"
            yield request

    async def _ensure_tokens(self) -> OAuthToken:
        async with self._lock:
            tokens = await self._storage.get_tokens()
            if tokens is not None:
                return tokens
            return await self._device_flow()

    async def _renew(self, stale: OAuthToken) -> OAuthToken:
        async with self._lock:
            current = await self._storage.get_tokens()
            if current is not None and current.access_token != stale.access_token:
                return current
            if stale.refresh_token:
                refreshed = await self._refresh(stale.refresh_token)
                if refreshed is not None:
                    return refreshed
            return await self._device_flow()

    async def _refresh(self, refresh_token: str) -> OAuthToken | None:
        async with httpx2.AsyncClient() as http:
            response = await http.post(
                GITHUB_TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={"Accept": "application/json"},
            )
        data = response.json()
        if "access_token" not in data:
            return None
        return await self._store(data)

    async def _store(self, data: dict) -> OAuthToken:
        tokens = OAuthToken(
            access_token=data["access_token"],
            token_type="Bearer",
            expires_in=data.get("expires_in"),
            scope=data.get("scope") or None,
            refresh_token=data.get("refresh_token"),
        )
        await self._storage.set_tokens(tokens)
        return tokens

    async def _device_flow(self) -> OAuthToken:
        if not self._interactive:
            raise AuthorizationRequiredError(self._server_name)
        async with httpx2.AsyncClient(headers={"Accept": "application/json"}) as http:
            response = await http.post(
                GITHUB_DEVICE_CODE_URL, data={"client_id": self._client_id}
            )
            data = response.json()
            if "device_code" not in data:
                raise OAuthFlowError(
                    f"device authorization failed: {data.get('error', response.status_code)}"
                )
            _prompt_authorization(
                self._server_name,
                f"open {data['verification_uri']} and enter code {data['user_code']}",
            )
            interval = float(data.get("interval", DEVICE_POLL_INTERVAL))
            loop = asyncio.get_running_loop()
            deadline = loop.time() + AUTHORIZATION_TIMEOUT
            while loop.time() < deadline:
                await asyncio.sleep(interval)
                poll = await http.post(
                    GITHUB_TOKEN_URL,
                    data={
                        "client_id": self._client_id,
                        "device_code": data["device_code"],
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    },
                )
                result = poll.json()
                if "access_token" in result:
                    return await self._store(result)
                error = result.get("error")
                if error == "authorization_pending":
                    continue
                if error == "slow_down":
                    interval += 5
                    continue
                raise OAuthFlowError(f"device authorization failed: {error}")
        raise OAuthFlowError("authorization timed out")


def build_auth(cfg: HttpServerConfig, interactive: bool) -> httpx2.Auth:
    if cfg.client_id:
        return build_oauth_provider(
            cfg.name, cfg.url, cfg.client_id, cfg.client_secret, interactive
        )
    default_client_id = DEFAULT_CLIENT_IDS.get(urlparse(cfg.url).hostname or "")
    if default_client_id:
        return GitHubDeviceAuth(cfg.name, default_client_id, interactive)
    return build_oauth_provider(cfg.name, cfg.url, interactive=interactive)


def build_oauth_provider(
    server_name: str,
    url: str,
    client_id: str | None = None,
    client_secret: str | None = None,
    interactive: bool = True,
) -> OAuthClientProvider:
    flow = OAuthBrowserFlow(server_name, interactive)
    auth_method = "client_secret_post" if client_secret else "none"
    metadata = OAuthClientMetadata(
        client_name="mini-agent",
        redirect_uris=[AnyUrl(flow.redirect_uri)],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method=auth_method,
    )
    storage: FileTokenStorage
    if client_id:
        client_info = OAuthClientInformationFull(
            client_id=client_id,
            client_secret=client_secret,
            **metadata.model_dump(exclude_none=True),
        )
        storage = _PreRegisteredStorage(server_name, client_info)
    else:
        storage = FileTokenStorage(server_name)
    return OAuthClientProvider(
        server_url=url,
        client_metadata=metadata,
        storage=storage,
        redirect_handler=flow.redirect_handler,
        callback_handler=flow.callback_handler,
    )
