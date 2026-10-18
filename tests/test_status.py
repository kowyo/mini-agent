from pathlib import Path

import pytest

from mini_agent.agent.mcp.tools import ServerStatus
from mini_agent.cli import status
from mini_agent.cli.status import format_usage_report
from mini_agent.cli.token import Usage
from mini_agent.config import _Config


def test_usage_report_shows_cache_hit_rate() -> None:
    usage = Usage(
        input_tokens=11_920,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=101_888,
        output_tokens=1_090,
    )

    report = format_usage_report(usage)

    assert report[-1].plain == "Cache Hit Rate: 89.5%"


def test_status_report_lists_mcp_servers(
    monkeypatch: pytest.MonkeyPatch, config_file: Path
) -> None:
    config_file.write_text(
        '[providers.deepseek]\nname = "DeepSeek"\n'
        'base_url = "https://api.deepseek.com/anthropic"\n'
        'api_key_env = "DEEPSEEK_API_KEY"\n'
    )
    monkeypatch.setattr(status, "config", _Config())
    monkeypatch.setattr(
        status,
        "server_statuses",
        [
            ServerStatus(name="chrome", tools=["click", "take_screenshot"]),
            ServerStatus(name="bad", error="did not start within 10s"),
        ],
    )
    lines = [str(line) for line in status.format_status_report("session-1")]
    header = lines.index("MCP Servers:")
    assert lines[header + 1] == "- chrome: 2 tools"
    assert lines[header + 2] == "  click, take_screenshot"
    assert lines[header + 3] == "- bad: failed (did not start within 10s)"


def test_usage_report_shows_zero_cache_hit_rate_without_cache_reads() -> None:
    usage = Usage(
        input_tokens=100,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=50,
    )

    report = format_usage_report(usage)

    assert report[-1].plain == "Cache Hit Rate: 0.0%"
