from rich.console import Console
from rich.text import Text

from ..config import DISTRIBUTION_NAME, DISTRIBUTION_VERSION, config
from .display.box import print_box
from .display.theme import LIGHT_HINT_STYLE_RICH

_console = Console()


def print_welcome_banner() -> None:
    version_line = Text.assemble(
        f" >_ {DISTRIBUTION_NAME} ",
        (f"(v{DISTRIBUTION_VERSION})", LIGHT_HINT_STYLE_RICH),
    )
    lines = [
        version_line,
        "",
        Text(f" model: {config.get_model()} {config.get_reasoning_effort()}"),
    ]
    print_box(_console, lines)
