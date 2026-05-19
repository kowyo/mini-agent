import json
import urllib.request
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


class _LimitsProvider:
    def __init__(self) -> None:
        self._cache_path = CONFIG_DIR / "models.json"
        self._cache: dict[str, dict] | None = None

    def _load(self) -> dict[str, dict]:
        if self._cache is None:
            try:
                with self._cache_path.open() as f:
                    self._cache = _parse_limits(json.load(f))
            except FileNotFoundError, json.JSONDecodeError:
                self._cache = {}
        return self._cache

    def get(self, model_id: str, key: str) -> int | None:
        return self._load().get(model_id, {}).get(key)

    def get_entry(self, model_id: str) -> dict:
        return self._load().get(model_id, {})

    def refresh(self) -> None:
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
            self._cache = _parse_limits(data)
        except OSError, json.JSONDecodeError:
            pass


_limits = _LimitsProvider()


def get_max_context_tokens(model_id: str) -> int | None:
    return _limits.get(model_id, "context")


def get_max_output_tokens(model_id: str) -> int | None:
    return _limits.get(model_id, "output")


def refresh_limits() -> None:
    _limits.refresh()


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
        entry = _limits.get_entry(model_id)
        context = entry.get("context")
        output = entry.get("output")
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
    refresh_limits()
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
