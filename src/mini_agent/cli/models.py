import json
import urllib.request
from datetime import UTC, datetime
from functools import lru_cache
from urllib.parse import urlparse

from anthropic.types import ModelInfo

from ..config import REASONING_EFFORT_LEVELS, client, config
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
    except Exception as e:
        print(f"Failed to fetch context token limit: {e}")
        return None


def get_max_output_tokens(model_id: str) -> int | None:
    try:
        return _fetch_limits().get(model_id, {}).get("output")
    except Exception as e:
        print(f"Failed to fetch output token limit: {e}")
        return None


def _fetch_models_sdk() -> list[ModelInfo]:
    models: list[ModelInfo] = []
    page = client.models.list(limit=100)
    models.extend(page.data)
    while page.has_more:
        page = page.get_next_page()
        models.extend(page.data)
    return sorted(models, key=lambda m: m.id)


def _fetch_models_manual() -> list[ModelInfo]:
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

    models: list[ModelInfo] = []
    for model_data in data.get("data", []):
        models.append(
            ModelInfo(
                id=model_data["id"],
                display_name=model_data.get("display_name") or model_data["id"],
                created_at=datetime.min.replace(tzinfo=UTC),
                type="model",
            )
        )
    return sorted(models, key=lambda m: m.id)


def fetch_models() -> list[ModelInfo]:
    try:
        return _fetch_models_sdk()
    except Exception:
        pass
    try:
        return _fetch_models_manual()
    except Exception:
        return []


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


_ENTER_MANUALLY = "Enter model ID manually..."


def select_model(models: list[ModelInfo]) -> str | None:
    current = config.get_model()
    ids = [m.id for m in models]
    selected_index = ids.index(current) if current in ids else 0

    items: list[ModelInfo | str] = [*models, _ENTER_MANUALLY]

    def fmt(item: ModelInfo | str) -> str:
        return item if isinstance(item, str) else format_model(item)

    result = select_from_list(
        items, "Select model", fmt, selected_index=selected_index, clear_after=True
    )
    if result is None:
        return None
    if isinstance(result, str):
        try:
            model_id = input("Model ID: ").strip()
        except KeyboardInterrupt, EOFError:
            print()
            return None
        print("\033[1A\033[2K", end="", flush=True)
        return model_id or None
    return result.id


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
        models = fetch_models()
    except Exception as e:
        print(f"Failed to fetch models: {e}\n")
        return

    if not models:
        print("No models available from API. Enter a model ID manually.")
        try:
            model_id = input("Model ID: ").strip()
        except KeyboardInterrupt, EOFError:
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

    model_id = select_model(models)

    if model_id is None:
        return

    effort_result = select_reasoning_effort()

    if effort_result is None:
        return

    config.save_model(model_id)
    config.save_reasoning_effort(effort_result)
    effort = config.get_reasoning_effort()
    print(f"Model set to {model_id} {effort}\n")
