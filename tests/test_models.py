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

    assert cache["deepseek-flash"]["limit"]["context"] == 1_000_000


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

    assert cache["claude-sonnet-4-6"]["limit"]["context"] == 1_000_000
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

    assert cache["deepseek-v4-flash"]["limit"]["output"] == 131_072


def test_lab_metadata_is_kept_without_official_provider() -> None:
    catalog = {
        "models": {
            "tencent/hy3-preview": {"limit": {"context": 262_144, "output": 262_144}}
        },
        "providers": {},
    }

    cache = _flatten_catalog(catalog)

    assert cache["tencent/hy3-preview"]["limit"]["context"] == 262_144
    assert cache["hy3-preview"]["limit"]["context"] == 262_144
