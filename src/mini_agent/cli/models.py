import json
import urllib.request
from functools import lru_cache
from urllib.parse import urlparse

from ..config import CONFIG_DIR, REASONING_EFFORT_LEVELS, client, config
from .display import clear_prompt_line
from .display.picker import select_from_list


def _parse_limits(data: dict) -> dict[str, dict]:
    limits: dict[str, dict] = {}
    for provider in data.values():
        for model_id, model in provider.get("models", {}).items():
            limit = model.get("limit", {})
            existing = limits.get(model_id, {})
            limits[model_id] = {
                "context": max(existing.get("context") or 0, limit.get("context") or 0)
                or None,
                "output": max(existing.get("output") or 0, limit.get("output") or 0)
                or None,
            }
    return limits


_MODELS_CACHE_PATH = CONFIG_DIR / "models.json"


def _load_cached_limits() -> dict[str, dict]:
    with _MODELS_CACHE_PATH.open() as f:
        data = json.load(f)
    return _parse_limits(data)


def _save_cache(data: dict) -> None:
    _MODELS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _MODELS_CACHE_PATH.open("w") as f:
        json.dump(data, f, indent=2)


@lru_cache(maxsize=1)
def _fetch_limits() -> dict[str, dict]:
    req = urllib.request.Request(
        "https://models.dev/api.json",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        _save_cache(data)
        return _parse_limits(data)
    except Exception:
        return _load_cached_limits()


def get_max_context_tokens(model_id: str) -> int | None:
    try:
        return _fetch_limits().get(model_id, {}).get("context")
    except Exception:
        return None


def get_max_output_tokens(model_id: str) -> int | None:
    try:
        return _fetch_limits().get(model_id, {}).get("output")
    except Exception:
        return None


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

    api_key = client.api_key or ""
    req = urllib.request.Request(
        url,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
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
        limits = _fetch_limits().get(model_id, {})
        context = limits.get("context")
        output = limits.get("output")
        if context is not None:
            parts.append(f"in:{context:,}")
        if output is not None:
            parts.append(f"out:{output:,}")
    except Exception:
        pass
    return "  ".join(parts)


_ENTER_MANUALLY = "Enter model ID manually..."


def select_model(model_ids: list[str]) -> str | None:
    current = config.get_model()
    selected_index = model_ids.index(current) if current in model_ids else 0

    items: list[str] = [*model_ids, _ENTER_MANUALLY]
    result = select_from_list(
        items,
        "Select model",
        format_model,
        selected_index=selected_index,
        clear_after=True,
    )
    if result is None:
        return None
    if result == _ENTER_MANUALLY:
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
