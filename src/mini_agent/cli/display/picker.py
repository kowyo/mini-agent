import shutil
from collections.abc import Callable, Sequence

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.layout import Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl

from .theme import LIGHT_HINT_STYLE, PROMPT_TOOLKIT_ACCENT_COLOR, SELECTED_STYLE


def select_from_list[T](
    items: Sequence[T],
    title: str,
    format_item: Callable[[T], str] = str,
    *,
    selected_index: int = 0,
    clear_after: bool = False,
    enable_search: bool = True,
) -> T | None:
    if not items:
        return None

    selected_index = max(0, min(selected_index, len(items) - 1))
    search_text = ""

    def get_filtered_items() -> list[tuple[int, T]]:
        """Return list of (original_index, item) tuples that match the search."""
        if not search_text:
            return [(i, item) for i, item in enumerate(items)]
        query = search_text.lower()
        return [
            (i, item)
            for i, item in enumerate(items)
            if query in format_item(item).replace("\n", " ").lower()
        ]

    def find_position_in_filtered(filtered: list[tuple[int, T]]) -> int:
        """Find the index of selected_index within the filtered list. Returns 0 if not found."""
        for idx, (orig_idx, _) in enumerate(filtered):
            if orig_idx == selected_index:
                return idx
        return 0

    def render() -> FormattedText:
        _, terminal_height = shutil.get_terminal_size(fallback=(80, 24))
        base_rows = max(terminal_height - 5, 1)  # -5 for title, search box, and hints
        show_hint = len(items) > base_rows

        item_rows = base_rows - 1 if show_hint else base_rows
        available_rows = max(item_rows, 1)

        filtered = get_filtered_items()

        # Find current position in filtered list
        current_filtered_index = find_position_in_filtered(filtered)

        start_index = max(0, current_filtered_index - available_rows // 2)
        end_index = min(len(filtered), start_index + available_rows)
        start_index = max(0, end_index - available_rows)

        fragments: list[tuple[str, str]] = [("", f"{title}\n")]

        # Show search box status
        if enable_search:
            if search_text:
                fragments.append(("", f"Search: {search_text}\n\n"))
            else:
                fragments.append((LIGHT_HINT_STYLE, "Type to search...\n\n"))

        if not filtered:
            fragments.append((LIGHT_HINT_STYLE, "  No matches found\n"))
        else:
            for idx in range(start_index, end_index):
                orig_idx, item = filtered[idx]
                label = format_item(item).replace("\n", " ")
                if orig_idx == selected_index:
                    fragments.append(
                        (
                            f"fg:{PROMPT_TOOLKIT_ACCENT_COLOR} {SELECTED_STYLE}",
                            f"> {label}\n",
                        )
                    )
                else:
                    fragments.append(("", f"  {label}\n"))

        if show_hint or (enable_search and search_text):
            fragments.append(("", "\n"))
            hints = []
            if show_hint:
                hints.append("↑/↓ to browse")
            if enable_search and search_text:
                hints.append(f"Showing {len(filtered)}/{len(items)} results")
                hints.append("Ctrl+U to clear search")
            fragments.append((LIGHT_HINT_STYLE, "  ".join(hints)))

        return FormattedText(fragments)

    bindings = KeyBindings()

    @bindings.add("up")
    def move_up(event: KeyPressEvent) -> None:
        nonlocal selected_index
        filtered = get_filtered_items()
        if not filtered:
            return
        # Find current position in filtered list
        current_pos = find_position_in_filtered(filtered)
        # Move to previous filtered item
        current_pos = (current_pos - 1) % len(filtered)
        selected_index = filtered[current_pos][0]
        event.app.invalidate()

    @bindings.add("down")
    def move_down(event: KeyPressEvent) -> None:
        nonlocal selected_index
        filtered = get_filtered_items()
        if not filtered:
            return
        # Find current position in filtered list
        current_pos = find_position_in_filtered(filtered)
        # Move to next filtered item
        current_pos = (current_pos + 1) % len(filtered)
        selected_index = filtered[current_pos][0]
        event.app.invalidate()

    @bindings.add("enter")
    def accept(event: KeyPressEvent) -> None:
        filtered = get_filtered_items()
        if filtered:
            # Find the selected item from filtered list
            for orig_idx, item in filtered:
                if orig_idx == selected_index:
                    event.app.exit(result=item)
                    return
            # If current selection not in filtered, select first filtered
            event.app.exit(result=filtered[0][1])
        else:
            event.app.exit(result=None)

    @bindings.add("escape")
    @bindings.add("c-c")
    def cancel(event: KeyPressEvent) -> None:
        event.app.exit(result=None)

    if enable_search:

        @bindings.add("c-u")
        def clear_search(event: KeyPressEvent) -> None:
            nonlocal search_text
            search_text = ""
            event.app.invalidate()

        @bindings.add("backspace")
        @bindings.add("c-h")
        def handle_backspace(event: KeyPressEvent) -> None:
            nonlocal search_text, selected_index
            if search_text:
                search_text = search_text[:-1]
                filtered = get_filtered_items()
                if filtered:
                    # Try to keep current selection if still in filtered list
                    for orig_idx, _ in filtered:
                        if orig_idx == selected_index:
                            break
                    else:
                        selected_index = filtered[0][0]
                event.app.invalidate()

        # Handle text input for search
        @bindings.add("<any>")
        def handle_text(event: KeyPressEvent) -> None:
            nonlocal search_text, selected_index
            key = event.key_sequence[0].key

            # Handle printable characters
            if len(key) == 1 and key.isprintable():
                search_text += key
                # Reset selection to first filtered item when searching
                filtered = get_filtered_items()
                if filtered:
                    selected_index = filtered[0][0]
                event.app.invalidate()

    application = Application(
        layout=Layout(Window(FormattedTextControl(render), always_hide_cursor=True)),
        key_bindings=bindings,
        erase_when_done=clear_after,
    )
    return application.run()
