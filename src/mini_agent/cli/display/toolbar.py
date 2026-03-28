import shutil

from prompt_toolkit.formatted_text import FormattedText

from ...config import get_model
from ..models import get_max_context_tokens
from ..token import token_tracker
from .picker import LIGHT_HINT_STYLE


def _format_token_right(
    total: tuple[int, int], last_round: tuple[int, int] | None
) -> str:
    right = f"↑{total[0]} ↓{total[1]}"
    context_limit = get_max_context_tokens(get_model())
    if context_limit and last_round is not None:
        used_tokens = last_round[0] + last_round[1]
        percent = min(100.0, (used_tokens / context_limit) * 100)
        right = f"{right} {percent:.1f}%"
    return f"{right}  "


def _pad_toolbar(left: str, right: str) -> str:
    term_width, _ = shutil.get_terminal_size(fallback=(80, 24))
    padding = " " * max(0, term_width - len(left) - len(right))
    return left + padding + right


def get_status_toolbar() -> FormattedText:
    left = f"  {get_model()}"
    usage = token_tracker.get()
    if usage is not None:
        right = _format_token_right(usage, token_tracker.get_last_round())
        return FormattedText([(LIGHT_HINT_STYLE, _pad_toolbar(left, right))])
    return FormattedText([(LIGHT_HINT_STYLE, left)])
