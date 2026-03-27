import shutil

from prompt_toolkit.formatted_text import FormattedText

from ...config import get_model
from ..models import get_max_context_tokens
from ..token_usage import get_token_usage
from .picker import LIGHT_HINT_STYLE


def _format_token_right(usage: tuple[int, int]) -> str:
    right = f"↑{usage[0]} ↓{usage[1]}"
    context_limit = get_max_context_tokens(get_model())
    if context_limit:
        used_tokens = usage[0] + usage[1]
        percent = min(100.0, (used_tokens / context_limit) * 100)
        right = f"{right} {percent:.1f}%"
    return f"{right}  "


def _pad_toolbar(left: str, right: str) -> str:
    term_width, _ = shutil.get_terminal_size(fallback=(80, 24))
    padding = " " * max(0, term_width - len(left) - len(right))
    return left + padding + right


def get_status_toolbar() -> FormattedText:
    left = f"  {get_model()}"
    usage = get_token_usage()
    if usage is not None:
        right = _format_token_right(usage)
        return FormattedText([(LIGHT_HINT_STYLE, _pad_toolbar(left, right))])
    return FormattedText([(LIGHT_HINT_STYLE, left)])
