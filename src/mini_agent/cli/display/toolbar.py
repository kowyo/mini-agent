import shutil

from prompt_toolkit.formatted_text import FormattedText

from ...config import config
from ..models import get_max_context_tokens
from ..token import Usage, token_tracker
from .picker import LIGHT_HINT_STYLE


def _format_tokens(count: int) -> str:
    if count < 1000:
        return str(count)
    if count < 10000:
        return f"{count / 1000:.1f}k"
    if count < 1_000_000:
        return f"{round(count / 1000)}k"
    if count < 10_000_000:
        return f"{count / 1_000_000:.1f}M"
    return f"{round(count / 1_000_000)}M"


def _format_token_right(total: Usage, last_round: Usage | None) -> str:
    parts = [
        f"↑{_format_tokens(total.input_tokens)}",
        f"↓{_format_tokens(total.output_tokens)}",
    ]
    if total.cache_read_input_tokens:
        parts.append(f"R{_format_tokens(total.cache_read_input_tokens)}")
    if total.cache_creation_input_tokens:
        parts.append(f"W{_format_tokens(total.cache_creation_input_tokens)}")
    right = " ".join(parts)
    context_limit = get_max_context_tokens(config.get_model())
    if context_limit and last_round is not None:
        used_tokens = last_round.total_input_tokens + last_round.output_tokens
        percent = min(100.0, (used_tokens / context_limit) * 100)
        right = f"{right} {percent:.1f}%/{_format_tokens(context_limit)}"
    return f"{right}  "


def _pad_toolbar(left: str, right: str) -> str:
    term_width, _ = shutil.get_terminal_size(fallback=(80, 24))
    padding = " " * max(0, term_width - len(left) - len(right))
    return left + padding + right


def get_status_toolbar() -> FormattedText:
    left = f"  {config.get_model()} {config.get_reasoning_effort()}"
    usage = token_tracker.get()
    if usage is not None:
        right = _format_token_right(usage, token_tracker.get_last_round())
        return FormattedText([(LIGHT_HINT_STYLE, _pad_toolbar(left, right))])
    return FormattedText([(LIGHT_HINT_STYLE, left)])
