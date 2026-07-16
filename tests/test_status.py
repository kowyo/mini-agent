from mini_agent.cli.status import format_usage_report
from mini_agent.cli.token import Usage


def test_usage_report_shows_cache_hit_rate() -> None:
    usage = Usage(
        input_tokens=11_920,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=101_888,
        output_tokens=1_090,
    )

    report = format_usage_report(usage)

    assert report[-1].plain == "Cache Hit Rate: 89.5%"


def test_usage_report_shows_zero_cache_hit_rate_without_cache_reads() -> None:
    usage = Usage(
        input_tokens=100,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=50,
    )

    report = format_usage_report(usage)

    assert report[-1].plain == "Cache Hit Rate: 0.0%"
