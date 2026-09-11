import gzip
import json
from pathlib import Path

import pytest

from mini_agent.cli import models

_CATALOG = {
    "models": {
        "deepseek/deepseek-v4.1-flash": {
            "limit": {"context": 1_000_000, "output": 384_000}
        },
        "tencent/hy3-preview": {"limit": {"context": 262_144, "output": 262_144}},
        "anthropic/claude-sonnet-4-6": {
            "limit": {"context": 1_000_000, "output": 128_000}
        },
    },
    "providers": {
        "deepseek": {
            "models": {
                "deepseek-flash": {"limit": {"context": 1_000_000, "output": 384_000}}
            }
        },
        "anthropic": {
            "models": {
                "claude-sonnet-4-6": {
                    "limit": {"context": 1_000_000, "output": 128_000}
                }
            }
        },
        "frogbot": {
            "models": {
                "claude-sonnet-4-6": {"limit": {"context": 200_000, "output": 64_000}}
            }
        },
    },
}


class _FakeResponse:
    def __init__(self, body: bytes, encoding: str | None) -> None:
        self._body = body
        self.headers = {"Content-Encoding": encoding} if encoding else {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


@pytest.mark.parametrize("encoding", [None, "gzip"])
def test_refresh_cache_resolves_limits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, encoding: str | None
) -> None:
    body = json.dumps(_CATALOG).encode()
    if encoding == "gzip":
        body = gzip.compress(body)
    monkeypatch.setattr(models, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        models.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _FakeResponse(body, encoding),
    )

    info = models._ModelInfo()
    info.refresh_cache()

    assert info.get_best_limit("deepseek-flash", "context") == 1_000_000
    assert info.get_best_limit("hy3-preview", "output") == 262_144
    assert info.get_best_limit("claude-sonnet-4-6", "output") == 128_000
    assert "deepseek-flash" not in json.loads((tmp_path / "catalog.json").read_text())


def test_corrupt_cache_is_refreshed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(models, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        models.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _FakeResponse(json.dumps(_CATALOG).encode(), None),
    )
    (tmp_path / "catalog.json").write_text("{ not json")

    info = models._ModelInfo()

    assert info.get_best_limit("deepseek-flash", "context") == 1_000_000
