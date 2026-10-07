import gzip
import json
import time
import urllib.request

from ..agent.providers import get_provider
from ..config import (
    CONFIG_DIR,
    config,
)
from .display import clear_prompt_line
from .display.picker import select_from_list

CATALOG_URL = "https://models.dev/catalog.json"


def _flatten_catalog(data: dict[str, dict]) -> dict[str, dict]:
    """Build a model-id to limits map from the models.dev catalog."""
    models: dict[str, dict] = data.get("models") or {}
    providers: dict[str, dict] = data.get("providers") or {}
    labs = {model_id.split("/")[0] for model_id in models}

    cache: dict[str, dict] = {}
    for model_id, metadata in models.items():
        limit = metadata.get("limit")
        if limit is not None:
            cache[model_id] = {"limit": limit}

    for provider_id, provider in providers.items():
        if provider_id not in labs:
            continue
        for model_id, model in (provider.get("models") or {}).items():
            limit = model.get("limit")
            if limit is None:
                continue
            cache[f"{provider_id}/{model_id}"] = {"limit": limit}

    return cache


class _ModelInfo:
    def __init__(self) -> None:
        self._cache_path = CONFIG_DIR / "catalog.json"
        self._cache: dict[str, dict] | None = None

    def _load_cache(self) -> dict[str, dict]:
        if self._cache is None:
            self._cache = self._read_cache()
        return self._cache

    def _read_cache(self) -> dict[str, dict]:
        try:
            return json.loads(self._cache_path.read_text())
        except FileNotFoundError, json.JSONDecodeError:
            self.refresh_cache(force=True)
            return self._cache or {}

    def get_best_limit(self, model_id: str, key: str) -> int | None:
        """Return the value for *key* (e.g. 'context' or 'output') for a given model."""
        cache = self._load_cache()
        model = cache.get(model_id)
        if model is None:
            for full_key, data in cache.items():
                if full_key.split("/")[-1] == model_id:
                    model = data
                    break
        if model is None:
            return None
        return (model.get("limit") or {}).get(key)

    def refresh_cache(self, force: bool = False) -> None:
        """Fetch the latest catalog from the remote API and update the local cache."""
        if not force and self._cache_path.exists():
            age = time.time() - self._cache_path.stat().st_mtime
            if age < 3600:
                return
        try:
            req = urllib.request.Request(
                CATALOG_URL,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Encoding": "gzip",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                data = json.loads(body)
            cache = _flatten_catalog(data)
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self._cache_path.open("w") as f:
                json.dump(cache, f)
            self._cache = cache
        except OSError, json.JSONDecodeError:
            pass


_model_info = _ModelInfo()


def get_max_context_tokens(model_id: str) -> int | None:
    return _model_info.get_best_limit(model_id, "context")


def get_max_output_tokens(model_id: str) -> int | None:
    return _model_info.get_best_limit(model_id, "output")


def fetch_models() -> list[str]:
    return get_provider().list_models()


def format_model(model_id: str) -> str:
    parts = [model_id]
    try:
        context = _model_info.get_best_limit(model_id, "context")
        output = _model_info.get_best_limit(model_id, "output")
        if context is not None:
            parts.append(f"in:{context:,}")
        if output is not None:
            parts.append(f"out:{output:,}")
    except Exception:
        pass
    return "  ".join(parts)


def select_model(model_ids: list[str]) -> str | None:
    current = config.get_model()
    selected_index = model_ids.index(current) if current in model_ids else 0

    items: list[str] = [*model_ids, "Enter model ID manually..."]
    result = select_from_list(
        items,
        "Select model",
        format_model,
        selected_index=selected_index,
        clear_after=True,
    )
    if result is None:
        return None
    if result == "Enter model ID manually...":
        try:
            model_id = input("Model ID: ").strip()
        except KeyboardInterrupt, EOFError:
            clear_prompt_line()
            print()
            return None
        clear_prompt_line()
        return model_id or None
    return result


def select_reasoning_effort() -> str | None:
    levels = get_provider().effort_levels
    current = config.get_reasoning_effort()
    selected_index = levels.index(current) if current in levels else 0
    return select_from_list(
        levels,
        "Select reasoning effort",
        selected_index=selected_index,
        clear_after=True,
        enable_search=False,
    )


def prompt_model() -> None:
    _model_info.refresh_cache()
    try:
        model_ids = fetch_models()
    except Exception as e:
        print(f"Failed to fetch models: {e}\n")
        return

    if not model_ids:
        try:
            model_id: str | None = input(
                "No models available from /v1/models. Please enter a model ID here: "
            ).strip()
            clear_prompt_line()
        except KeyboardInterrupt, EOFError:
            clear_prompt_line()
            print()
            return
        if not model_id:
            return
        effort_result = select_reasoning_effort()
        if effort_result is None:
            return
        config.save_model(model_id)
        config.save_reasoning_effort(effort_result)
        effort = config.get_reasoning_effort()
        print(f"Model set to {model_id} {effort}\n")
        return

    model_id = select_model(model_ids)

    if model_id is None:
        return

    effort_result = select_reasoning_effort()

    if effort_result is None:
        return

    config.save_model(model_id)
    config.save_reasoning_effort(effort_result)
    effort = config.get_reasoning_effort()
    print(f"Model set to {model_id} {effort}\n")
