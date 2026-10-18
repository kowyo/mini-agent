import hashlib
import re

from ..transcript import AssistantMessage, Message, ToolCall

_TOOL_ID_PATTERN = re.compile(r"[^A-Za-z0-9_-]")
_MAX_TOOL_ID_LENGTH = 64


def normalize_id(value: str) -> str:
    base = _TOOL_ID_PATTERN.sub("_", value).strip("_")[:_MAX_TOOL_ID_LENGTH]
    return base or "tool"


def normalize_foreign_tool_ids(
    messages: list[Message],
    *,
    provider_id: str,
    api_type: str,
    model: str,
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for message in messages:
        if not isinstance(message, AssistantMessage):
            continue
        foreign = (
            message.provider != provider_id
            or message.api_type != api_type
            or message.model != model
        )
        if not foreign:
            continue
        for block in message.content:
            if not isinstance(block, ToolCall):
                continue
            base = normalize_id(block.id)
            normalized = base
            if normalized in used and mapping.get(block.id) != normalized:
                digest = hashlib.sha256(block.id.encode()).hexdigest()[:8]
                normalized = f"{base[: _MAX_TOOL_ID_LENGTH - 9]}_{digest}"
            mapping[block.id] = normalized
            used.add(normalized)
    return mapping
