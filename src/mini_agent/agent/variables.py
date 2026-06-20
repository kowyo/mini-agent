import re

from ..config import config

_VAR_RE = re.compile(r"\$([A-Z_][A-Z0-9_]*|\{[A-Z_][A-Z0-9_]*\})")


def get_variables() -> dict[str, str]:
    return {"MODEL_NAME": config.get_model()}


def substitute_variables(text: str, variables: dict[str, str] | None = None) -> str:
    if variables is None:
        variables = get_variables()

    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key.startswith("{") and key.endswith("}"):
            key = key[1:-1]
        return variables.get(key, m.group(0))

    return _VAR_RE.sub(repl, text)
