import sys

import pytest

from mini_agent.cli import main as cli


def test_print_runs_when_resume_finds_no_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []
    monkeypatch.setattr(sys, "argv", ["mini", "-p", "hello", "--resume"])
    monkeypatch.setattr(cli.config, "get_provider", lambda: None)
    monkeypatch.setattr(cli._session_manager, "list_sessions", list)
    monkeypatch.setattr(cli, "_run_non_interactive", prompts.append)
    monkeypatch.setattr(cli, "shutdown_mcp", lambda: None)

    cli.main()

    assert prompts == ["hello"]
