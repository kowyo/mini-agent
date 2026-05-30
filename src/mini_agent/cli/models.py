import json
import urllib.request
from urllib.parse import urlparse

from ..config import (
    CONFIG_DIR,
    DEFAULT_PROVIDERS,
    REASONING_EFFORT_LEVELS,
    client,
    config,
)
from .display import clear_prompt_line
from .display.picker import select_from_list


def _get_provider_hint(model_id: str) -> str | None:
    for provider_id, prefixes in DEFAULT_PROVIDERS.items():
        if model_id.startswith(tuple(prefixes)):
            return provider_id
    return None


def _get_limit_for_provider(
    cache: dict[str, dict], provider_id: str, model_id: str, key: str
) -> int | None:
    provider = cache.get(provider_id)
    if not provider:
        return None
    model = (provider.get("models") or {}).get(model_id)
    if not model:
        return None
    return (model.get("limit") or {}).get(key)


class _ModelInfo:
    def __init__(self) -> None:
        self._cache_path = CONFIG_DIR / "models.json"
        self._cache: dict[str, dict] | None = None

    def _load_cache(self) -> dict[str, dict]:
        """Load the cache from disk, returning an empty dict on failure."""
        if self._cache is None:
            try:
                with self._cache_path.open() as f:
                    self._cache = json.load(f)
            except FileNotFoundError, json.JSONDecodeError:
                self._cache = {}
        return self._cache

    def get_best_limit(self, model_id: str, key: str) -> int | None:
        """Return the maximum value for *key* (e.g. 'context' or 'output') across all providers for a given model."""
        cache = self._load_cache()

        # 1. Try with user-specified provider
        user_provider = config.get_provider()
        if user_provider:
            best = _get_limit_for_provider(cache, user_provider, model_id, key)
            if best is not None:
                return best

        # 2. Fall back to prefix matching using DEFAULT_PROVIDERS
        provider_hint = _get_provider_hint(model_id)
        if provider_hint and provider_hint != user_provider:
            best = _get_limit_for_provider(cache, provider_hint, model_id, key)
            if best is not None:
                return best

        # 3. Fall back to searching across ALL providers in the catalog
        best = None
        for provider_id, provider in cache.items():
            if provider_id in (user_provider, provider_hint):
                continue
            model = (provider.get("models") or {}).get(model_id)
            if model is None:
                continue
            value = (model.get("limit") or {}).get(key)
            if value is not None and (best is None or value > best):
                best = value
        return best

    def refresh_cache(self) -> None:
        """Fetch the latest model data from the remote API and update the local cache."""
        try:
            req = urllib.request.Request(
                "https://models.dev/api.json",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self._cache_path.open("w") as f:
                json.dump(data, f)
            self._cache = data
        except OSError, json.JSONDecodeError:
            pass


_model_info = _ModelInfo()


def get_max_context_tokens(model_id: str) -> int | None:
    return _model_info.get_best_limit(model_id, "context")


def get_max_output_tokens(model_id: str) -> int | None:
    return _model_info.get_best_limit(model_id, "output")


def _fetch_models_sdk() -> list[str]:
    model_ids: list[str] = []
    page = client.models.list(limit=100)
    model_ids.extend(m.id for m in page.data)
    while page.has_more:
        page = page.get_next_page()
        model_ids.extend(m.id for m in page.data)
    return sorted(model_ids)


def _fetch_models_manual() -> list[str]:
    parsed = urlparse(str(client.base_url))
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    url = f"{base_url}/v1/models"

    headers: dict[str, str] = {"anthropic-version": "2023-06-01"}
    if client.auth_token:
        headers["Authorization"] = f"Bearer {client.auth_token}"
    elif client.api_key:
        headers["x-api-key"] = client.api_key

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())

    return sorted(m["id"] for m in data.get("data", []))


def fetch_models() -> list[str]:
    try:
        return _fetch_models_sdk()
    except Exception:
        pass
    try:
        return _fetch_models_manual()
    except Exception:
        return []


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
