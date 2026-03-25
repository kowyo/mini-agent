import shutil
from collections.abc import Callable, Sequence

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl

from .theme import LIGHT_HINT_STYLE, SELECTED_STYLE


def select_from_list[T](
    items: Sequence[T],
    title: str,
    format_item: Callable[[T], str] = str,
    *,
    selected_index: int = 0,
) -> T | None:
    if not items:
        return None

    selected_index = max(0, min(selected_index, len(items) - 1))

    def render() -> FormattedText:
        _, terminal_height = shutil.get_terminal_size(fallback=(80, 24))
        base_rows = max(terminal_height - 4, 1)
        show_hint = len(items) > base_rows

        item_rows = base_rows - 1 if show_hint else base_rows
        available_rows = max(item_rows, 1)

        start_index = max(0, selected_index - available_rows // 2)
        end_index = min(len(items), start_index + available_rows)
        start_index = max(0, end_index - available_rows)

        fragments: list[tuple[str, str]] = [("", f"{title}\n\n")]

        for index in range(start_index, end_index):
            label = format_item(items[index]).replace("\n", " ")
            if index == selected_index:
                fragments.append((SELECTED_STYLE, f"> {label}\n"))
            else:
                fragments.append(("", f"  {label}\n"))

        if show_hint:
            fragments.append(("", "\n"))
            fragments.append((LIGHT_HINT_STYLE, "↑/↓ to browse"))

        return FormattedText(fragments)

    bindings = KeyBindings()

    @bindings.add("up")
    def move_up(event: KeyPressEvent) -> None:
        nonlocal selected_index
        selected_index = (selected_index - 1) % len(items)
        event.app.invalidate()

    @bindings.add("down")
    def move_down(event: KeyPressEvent) -> None:
        nonlocal selected_index
        selected_index = (selected_index + 1) % len(items)
        event.app.invalidate()

    @bindings.add("enter")
    def accept(event: KeyPressEvent) -> None:
        event.app.exit(result=items[selected_index])

    @bindings.add("escape")
    @bindings.add("c-c")
    def cancel(event: KeyPressEvent) -> None:
        event.app.exit(result=None)

    application = Application(
        layout=Layout(Window(FormattedTextControl(render), always_hide_cursor=True)),
        key_bindings=bindings,
    )
    return application.run()
