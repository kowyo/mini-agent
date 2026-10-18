import json
from pathlib import Path
from typing import Any

import pytest

from mini_agent.agent.api import response as response_api
from mini_agent.agent.api.base import TurnRequest
from mini_agent.agent.transcript import ToolSpec, Transcript, UserMessage
from mini_agent.chatgpt import credentials
from mini_agent.cli import models
from mini_agent.config import CHATGPT_PROVIDER, _Config


def test_chatgpt_provider_is_built_in(config_file: Path) -> None:
    config = _Config()

    assert config.get_provider() == CHATGPT_PROVIDER
    assert CHATGPT_PROVIDER.api_type == "response"
    assert CHATGPT_PROVIDER.auth_type == "chatgpt"


def test_get_api_key_uses_chatgpt_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mini_agent import config

    monkeypatch.setattr(credentials, "get_access_token", lambda: "chatgpt-token")

    assert config.get_api_key(CHATGPT_PROVIDER) == "chatgpt-token"


def test_chatgpt_model_catalog_filters_visibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "models": [
            {"slug": "gpt-5.4", "visibility": "list"},
            {"slug": "internal", "visibility": "hidden"},
        ]
    }

    class FakeResponse:
        def read(self) -> bytes:
            return json.dumps(payload).encode()

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            pass

    monkeypatch.setattr(models.config, "get_provider", lambda: CHATGPT_PROVIDER)
    monkeypatch.setattr(models, "get_api_key", lambda provider: "token")
    monkeypatch.setattr(
        models.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse()
    )

    assert models._fetch_models() == ["gpt-5.4"]


def test_chatgpt_requests_use_additional_tools_and_omit_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeManager:
        def __enter__(self) -> object:
            return object()

        def __exit__(self, *args: object) -> None:
            pass

    class FakeResponses:
        def stream(self, **kwargs: object) -> FakeManager:
            captured.update(kwargs)
            return FakeManager()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(
        response_api, "_reasoning_config", lambda *args: (None, None, False)
    )
    monkeypatch.setattr(response_api, "get_responses_client", lambda: FakeClient())

    request = TurnRequest(
        transcript=Transcript(
            system="system",
            tools=[
                ToolSpec(name="bash", description="Run", parameters={"type": "object"})
            ],
            messages=[UserMessage(content="hi")],
        ),
        provider=CHATGPT_PROVIDER,
        model="gpt-5.4",
        reasoning_effort="high",
        session_id="session",
        max_output_tokens=1024,
    )

    with response_api.ResponsesBackend().run_turn(request):
        pass

    assert captured["input"][0]["type"] == "additional_tools"
    assert captured["input"][0]["tools"][0]["name"] == "bash"
    assert "tools" not in captured
    assert "max_output_tokens" not in captured
    assert captured["prompt_cache_key"] == "session"


def test_chatgpt_reasoning_is_enabled_without_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reasoning, include, enabled = response_api._reasoning_config(
        "unknown-model", "high", "chatgpt"
    )

    assert reasoning == {"effort": "high", "summary": "auto"}
    assert include == ["reasoning.encrypted_content"]
    assert enabled is True
