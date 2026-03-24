from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl

from .config import client, get_model, save_model


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

    def render() -> FormattedText:
        fragments: list[tuple[str, str]] = [
            ("", "Select model\n\n"),
        ]
        for index, model_id in enumerate(models):
            prefix = "> " if index == selected_index else "  "
            fragments.append(("", f"{prefix}{model_id}\n"))
        return FormattedText(fragments)

    bindings = KeyBindings()

    @bindings.add("up")
    def move_up(event: KeyPressEvent) -> None:
        nonlocal selected_index
        selected_index = (selected_index - 1) % len(models)
        event.app.invalidate()

    @bindings.add("down")
    def move_down(event: KeyPressEvent) -> None:
        nonlocal selected_index
        selected_index = (selected_index + 1) % len(models)
        event.app.invalidate()

    @bindings.add("enter")
    def accept(event: KeyPressEvent) -> None:
        event.app.exit(result=models[selected_index])

    @bindings.add("escape")
    @bindings.add("c-c")
    def cancel(event: KeyPressEvent) -> None:
        event.app.exit(result=None)

    application = Application(
        layout=Layout(Window(FormattedTextControl(render), always_hide_cursor=True)),
        key_bindings=bindings,
        full_screen=False,
        mouse_support=False,
        style=None,
    )
    return application.run()


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
