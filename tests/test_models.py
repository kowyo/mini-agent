import gzip
import json
from pathlib import Path

import pytest

from mini_agent.cli import models
from mini_agent.cli.models import _flatten_catalog


def test_official_provider_alias_is_resolved() -> None:
    catalog = {
        "models": {
            "deepseek/deepseek-v4.1-flash": {
                "limit": {"context": 1_000_000, "output": 384_000}
            }
        },
        "providers": {
            "deepseek": {
                "models": {
                    "deepseek-flash": {
                        "limit": {"context": 1_000_000, "output": 384_000}
                    }
                }
            }
        },
    }

    cache = _flatten_catalog(catalog)

    assert cache["deepseek/deepseek-flash"]["limit"]["context"] == 1_000_000
    assert "deepseek-flash" not in cache


def test_non_official_provider_is_ignored() -> None:
    catalog = {
        "models": {
            "anthropic/claude-sonnet-4-6": {
                "limit": {"context": 1_000_000, "output": 128_000}
            }
        },
        "providers": {
            "anthropic": {
                "models": {
                    "claude-sonnet-4-6": {
                        "limit": {"context": 1_000_000, "output": 128_000}
                    }
                }
            },
            "frogbot": {
                "models": {
                    "claude-sonnet-4-6": {
                        "limit": {"context": 200_000, "output": 64_000}
                    }
                }
            },
        },
    }

    cache = _flatten_catalog(catalog)

    assert cache["anthropic/claude-sonnet-4-6"]["limit"]["context"] == 1_000_000
    assert "frogbot/claude-sonnet-4-6" not in cache


def test_official_provider_overrides_lab_metadata() -> None:
    catalog = {
        "models": {
            "deepseek/deepseek-v4-flash": {
                "limit": {"context": 1_000_000, "output": 384_000}
            }
        },
        "providers": {
            "deepseek": {
                "models": {
                    "deepseek-v4-flash": {
                        "limit": {"context": 1_000_000, "output": 131_072}
                    }
                }
            }
        },
    }

    cache = _flatten_catalog(catalog)

    assert cache["deepseek/deepseek-v4-flash"]["limit"]["output"] == 131_072


def test_lab_metadata_is_kept_without_official_provider() -> None:
    catalog = {
        "models": {
            "tencent/hy3-preview": {"limit": {"context": 262_144, "output": 262_144}}
        },
        "providers": {},
    }

    cache = _flatten_catalog(catalog)

    assert cache["tencent/hy3-preview"]["limit"]["context"] == 262_144
    assert "hy3-preview" not in cache


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
def test_refresh_cache_writes_limits_from_catalog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, encoding: str | None
) -> None:
    catalog = {
        "models": {
            "deepseek/deepseek-v4.1-flash": {
                "limit": {"context": 1_000_000, "output": 384_000}
            }
        },
        "providers": {
            "deepseek": {
                "models": {
                    "deepseek-flash": {
                        "limit": {"context": 1_000_000, "output": 384_000}
                    }
                }
            }
        },
    }
    body = json.dumps(catalog).encode()
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
    assert json.loads((tmp_path / "catalog.json").read_text()) == {
        "deepseek/deepseek-v4.1-flash": {
            "limit": {"context": 1_000_000, "output": 384_000}
        },
        "deepseek/deepseek-flash": {"limit": {"context": 1_000_000, "output": 384_000}},
    }


def test_corrupt_cache_is_refreshed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    catalog = {
        "models": {
            "deepseek/deepseek-v4.1-flash": {
                "limit": {"context": 1_000_000, "output": 384_000}
            }
        },
        "providers": {
            "deepseek": {
                "models": {
                    "deepseek-flash": {
                        "limit": {"context": 1_000_000, "output": 384_000}
                    }
                }
            }
        },
    }
    monkeypatch.setattr(models, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        models.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _FakeResponse(json.dumps(catalog).encode(), None),
    )
    (tmp_path / "catalog.json").write_text("{ not json")

    info = models._ModelInfo()

    assert info.get_best_limit("deepseek-flash", "context") == 1_000_000
