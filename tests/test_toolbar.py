from mini_agent.cli.display.toolbar import _format_token_right
from mini_agent.cli.token import Usage


def test_toolbar_shows_cache_hit_rate() -> None:
    usage = Usage(
        input_tokens=11_920,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=101_888,
        output_tokens=1_090,
    )

    assert _format_token_right(usage, None) == "↑12k ↓1.1k R102k CR89.5%  "


def test_toolbar_hides_cache_hit_rate_without_cache_reads() -> None:
    usage = Usage(
        input_tokens=100,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=50,
    )

    assert _format_token_right(usage, None) == "↑100 ↓50  "
