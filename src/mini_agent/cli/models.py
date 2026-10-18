import gzip
import json
import time
import urllib.request
from urllib.parse import urlparse

from ..config import (
    CONFIG_DIR,
    REASONING_EFFORT_LEVELS,
    config,
    get_api_key,
    get_client,
    get_responses_client,
)
from .display import clear_prompt_line
from .display.picker import select_from_list

_CATALOG_URL = "https://models.dev/catalog.json"


def _flatten_catalog(data: dict[str, dict]) -> dict[str, dict]:
    """Build a model-id to limits map from the models.dev catalog."""
    models: dict[str, dict] = data.get("models") or {}
    providers: dict[str, dict] = data.get("providers") or {}
    labs = {model_id.split("/")[0] for model_id in models}

    def entry(metadata: dict) -> dict | None:
        limit = metadata.get("limit")
        if limit is None:
            return None
        return {
            "limit": limit,
            "reasoning": metadata.get("reasoning"),
            "reasoning_options": metadata.get("reasoning_options"),
        }

    cache: dict[str, dict] = {}
    for model_id, metadata in models.items():
        if (value := entry(metadata)) is not None:
            cache[model_id] = value

    for provider_id, provider in providers.items():
        if provider_id not in labs:
            continue
        for model_id, model in (provider.get("models") or {}).items():
            if (value := entry(model)) is not None:
                cache[f"{provider_id}/{model_id}"] = value

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
            self._refresh_cache(force=True)
            return self._cache or {}

    def _get(self, model_id: str) -> dict | None:
        cache = self._load_cache()
        model = cache.get(model_id)
        if model is None:
            for full_key, data in cache.items():
                if full_key.split("/")[-1] == model_id:
                    model = data
                    break
        return model

    def _get_best_limit(self, model_id: str, key: str) -> int | None:
        """Return the value for *key* (e.g. 'context' or 'output') for a given model."""
        model = self._get(model_id)
        if model is None:
            return None
        return (model.get("limit") or {}).get(key)

    def get_model_reasoning(self, model_id: str) -> bool | None:
        model = self._get(model_id)
        if model is None:
            return None
        value = model.get("reasoning")
        return value if isinstance(value, bool) else None

    def get_reasoning_efforts(self, model_id: str) -> list[str] | None:
        model = self._get(model_id)
        if model is None:
            return None
        for option in model.get("reasoning_options") or []:
            if isinstance(option, dict) and option.get("type") == "effort":
                values = option.get("values")
                if isinstance(values, list):
                    return [str(value) for value in values]
        return None

    def _refresh_cache(self, force: bool = False) -> None:
        """Fetch the latest catalog from the remote API and update the local cache."""
        if not force and self._cache_path.exists():
            age = time.time() - self._cache_path.stat().st_mtime
            if age < 3600:
                return
        try:
            req = urllib.request.Request(
                _CATALOG_URL,
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
    return _model_info._get_best_limit(model_id, "context")


def get_max_output_tokens(model_id: str) -> int | None:
    return _model_info._get_best_limit(model_id, "output")


def get_model_reasoning(model_id: str) -> bool | None:
    return _model_info.get_model_reasoning(model_id)


def get_reasoning_efforts(model_id: str) -> list[str] | None:
    return _model_info.get_reasoning_efforts(model_id)


def _fetch_models_sdk() -> list[str]:
    model_ids: list[str] = []
    page = get_client().models.list(limit=100)
    model_ids.extend(m.id for m in page.data)
    while page.has_more:
        page = page.get_next_page()
        model_ids.extend(m.id for m in page.data)
    return sorted(model_ids)


def _fetch_models_manual() -> list[str]:
    client = get_client()
    parsed = urlparse(str(client.base_url))
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    url = f"{base_url}/v1/models"

    headers: dict[str, str] = {
        "anthropic-version": "2023-06-01",
        "Authorization": f"Bearer {client.auth_token}",
    }

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())

    return sorted(m["id"] for m in data.get("data", []))


def _fetch_response_models_sdk() -> list[str]:
    page = get_responses_client().models.list()
    return sorted(model.id for model in page.data)


def _fetch_response_models_manual() -> list[str]:
    client = get_responses_client()
    url = f"{str(client.base_url).rstrip('/')}/models"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {client.api_key}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return sorted(item["id"] for item in data.get("data", []))


def _fetch_chatgpt_models() -> list[str]:
    provider = config.get_provider()
    url = f"{provider.base_url.rstrip('/')}/models"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {get_api_key(provider)}",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    models = data.get("models", [])
    return sorted(
        item["slug"]
        for item in models
        if isinstance(item, dict)
        and item.get("visibility") == "list"
        and isinstance(item.get("slug"), str)
    )


def _fetch_models() -> list[str]:
    provider = config.get_provider()
    if provider.auth_type == "chatgpt":
        return _fetch_chatgpt_models()
    if provider.api_type == "response":
        try:
            return _fetch_response_models_sdk()
        except Exception:
            pass
        try:
            return _fetch_response_models_manual()
        except Exception:
            return []
    try:
        return _fetch_models_sdk()
    except Exception:
        pass
    try:
        return _fetch_models_manual()
    except Exception:
        return []


def _format_model(model_id: str) -> str:
    parts = [model_id]
    try:
        context = _model_info._get_best_limit(model_id, "context")
        output = _model_info._get_best_limit(model_id, "output")
        if context is not None:
            parts.append(f"in:{context:,}")
        if output is not None:
            parts.append(f"out:{output:,}")
    except Exception:
        pass
    return "  ".join(parts)


def _select_model(model_ids: list[str]) -> str | None:
    current = config.get_model()
    selected_index = model_ids.index(current) if current in model_ids else 0

    items: list[str] = [*model_ids, "Enter model ID manually..."]
    result = select_from_list(
        items,
        "Select model",
        _format_model,
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


def _select_reasoning_effort() -> str | None:
    current = config.get_reasoning_effort()
    selected_index = (
        REASONING_EFFORT_LEVELS.index(current)
        if current in REASONING_EFFORT_LEVELS
        else 0
    )
    return select_from_list(
        REASONING_EFFORT_LEVELS,
        "Select reasoning effort",
        selected_index=selected_index,
        clear_after=True,
        enable_search=False,
    )


def prompt_model() -> None:
    _model_info._refresh_cache()
    try:
        model_ids = _fetch_models()
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
        effort_result = _select_reasoning_effort()
        if effort_result is None:
            return
        config.save_model(model_id)
        config.save_reasoning_effort(effort_result)
        effort = config.get_reasoning_effort()
        print(f"Model set to {model_id} {effort}\n")
        return

    model_id = _select_model(model_ids)

    if model_id is None:
        return

    effort_result = _select_reasoning_effort()

    if effort_result is None:
        return

    config.save_model(model_id)
    config.save_reasoning_effort(effort_result)
    effort = config.get_reasoning_effort()
    print(f"Model set to {model_id} {effort}\n")
