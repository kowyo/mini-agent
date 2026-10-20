import subprocess
import sys

DEFERRED_MODULES = ("anthropic", "mcp", "mcp_types", "PIL", "pydantic")


def test_cli_import_defers_heavy_modules() -> None:
    code = (
        "import sys\n"
        "import mini_agent.cli.main\n"
        f"print(*(name for name in {DEFERRED_MODULES!r} if name in sys.modules))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""
