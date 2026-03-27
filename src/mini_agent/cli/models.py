import json
import urllib.request
from functools import lru_cache

from anthropic.types import ModelInfo

from ..config import client, get_model, save_model
from .display.picker import select_from_list


@lru_cache(maxsize=1)
def _fetch_limits() -> dict[str, dict]:
    req = urllib.request.Request(
        "https://models.dev/api.json",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read())
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


def fetch_models() -> list[ModelInfo]:
    models: list[ModelInfo] = []
    page = client.models.list(limit=100)
    models.extend(page.data)
    while page.has_more:
        page = page.get_next_page()
        models.extend(page.data)
    return sorted(models, key=lambda m: m.id)


def format_model(model: ModelInfo) -> str:
    parts = [model.id]
    try:
        limits = _fetch_limits().get(model.id, {})
        context = limits.get("context")
        output = limits.get("output")
        if context is not None:
            parts.append(f"in:{context:,}")
        if output is not None:
            parts.append(f"out:{output:,}")
    except Exception:
        pass
    return "  ".join(parts)


def select_model(models: list[ModelInfo]) -> ModelInfo | None:
    current = get_model()
    ids = [m.id for m in models]
    selected_index = ids.index(current) if current in ids else 0
    return select_from_list(
        models, "Select model", format_model, selected_index=selected_index
    )


def prompt_model() -> None:
    try:
        models = fetch_models()
    except Exception as e:
        print(f"Failed to fetch models: {e}\n")
        return

    if not models:
        print("No models available.\n")
        return

    result = select_model(models)
    print()

    if result is None:
        return

    save_model(result.id)
    print(f"Model set to {result.id}\n")
