from ..config import client, get_model, save_model
from .display.picker import select_from_list


def fetch_models() -> list[str]:
    model_ids: list[str] = []
    page = client.models.list(limit=100)
    model_ids.extend(m.id for m in page.data)
    while page.has_more:
        page = page.get_next_page()
        model_ids.extend(m.id for m in page.data)
    return sorted(model_ids)


def select_model(models: list[str]) -> str | None:
    current = get_model()
    selected_index = models.index(current) if current in models else 0
    return select_from_list(models, "Select model", selected_index=selected_index)


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

    save_model(result)
    print(f"Model set to {result}\n")
