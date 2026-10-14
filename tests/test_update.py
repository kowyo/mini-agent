import io
import json
from types import SimpleNamespace

import pytest

from mini_agent.cli import update

WHEEL_URL = "https://github.com/kowyo/mini-agent/releases/download/v9.0.0/mini_agent-9.0.0-py3-none-any.whl"


def _release(tag: str) -> dict:
    return {
        "tag_name": tag,
        "assets": [
            {"name": "mini_agent-9.0.0.tar.gz", "browser_download_url": "sdist"},
            {
                "name": "mini_agent-9.0.0-py3-none-any.whl",
                "browser_download_url": WHEEL_URL,
            },
        ],
    }


@pytest.fixture
def uv_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(update.subprocess, "run", fake_run)
    return calls


def _serve_release(monkeypatch: pytest.MonkeyPatch, tag: str) -> None:
    monkeypatch.setattr(
        update.urllib.request,
        "urlopen",
        lambda *args, **kwargs: io.BytesIO(json.dumps(_release(tag)).encode()),
    )


def test_installs_latest_wheel_with_uv(
    monkeypatch: pytest.MonkeyPatch, uv_calls: list[list[str]]
) -> None:
    _serve_release(monkeypatch, "v9.0.0")
    monkeypatch.setattr(update.sys, "platform", "darwin")

    assert update.run_update() == 0
    assert uv_calls == [["uv", "tool", "install", "--force", WHEEL_URL]]


def test_skips_install_when_up_to_date(
    monkeypatch: pytest.MonkeyPatch, uv_calls: list[list[str]]
) -> None:
    _serve_release(monkeypatch, f"v{update.DISTRIBUTION_VERSION}")

    assert update.run_update() == 0
    assert uv_calls == []


def test_windows_prints_installer_command_instead_of_installing(
    monkeypatch: pytest.MonkeyPatch,
    uv_calls: list[list[str]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _serve_release(monkeypatch, "v9.0.0")
    monkeypatch.setattr(update.sys, "platform", "win32")

    assert update.run_update() == 0
    assert uv_calls == []
    assert update.WINDOWS_UPDATE_COMMAND in capsys.readouterr().out
