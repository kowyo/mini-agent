import json
from collections.abc import Iterator
from typing import Any, cast

from openai import OpenAI

from ...cli.token import Usage
from ...config import get_responses_client
from ..transcript import (
    AssistantMessage,
    ImageBlock,
    TextBlock,
    ThinkingBlock,
    ToolCall,
    ToolResultMessage,
    ToolSpec,
    UserMessage,
)
from ..transcript import (
    Message as TranscriptMessage,
)
from .base import (
    ApiBackend,
    ApiError,
    BlockEnd,
    StreamEvent,
    TurnRequest,
    TurnStream,
)
from .base import (
    TextDelta as NeutralTextDelta,
)
from .base import (
    ThinkingDelta as NeutralThinkingDelta,
)
from .ids import normalize_foreign_tool_ids

_MIN_OUTPUT_TOKENS = 16


def _mapped_effort(effort: str) -> str:
    return {
        "disabled": "none",
        "adaptive": "medium",
    }.get(effort, effort)


def _reasoning_config(
    model: str, effort: str, auth_type: str = "api_key"
) -> tuple[dict[str, Any] | None, list[str] | None, bool]:
    from ...cli.models import get_model_reasoning, get_reasoning_efforts

    if auth_type != "chatgpt" and get_model_reasoning(model) is not True:
        return None, None, False
    if effort == "disabled":
        return {"effort": "none"}, None, False
    if effort == "adaptive":
        return None, None, True
    values = get_reasoning_efforts(model)
    mapped = _mapped_effort(effort)
    if values and mapped not in values:
        mapped = "medium" if "medium" in values else values[-1]
    return (
        {"effort": mapped, "summary": "auto"},
        ["reasoning.encrypted_content"],
        True,
    )


def _tool_output(message: ToolResultMessage) -> str | list[dict[str, Any]]:
    texts = [block.text for block in message.content if isinstance(block, TextBlock)]
    images = [block for block in message.content if isinstance(block, ImageBlock)]
    text = "\n".join(texts)
    if message.is_error:
        text = f"Error: {text}" if text else "Error"
    if not images:
        return text or "(no content)"
    output: list[dict[str, Any]] = []
    if text:
        output.append({"type": "input_text", "text": text})
    output.extend(
        {
            "type": "input_image",
            "detail": "auto",
            "image_url": f"data:{image.mime_type};base64,{image.data}",
        }
        for image in images
    )
    return output


def _text_signature(block: TextBlock) -> dict[str, Any] | None:
    if not block.signature:
        return None
    try:
        data = json.loads(block.signature)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _assistant_output(
    message: AssistantMessage,
    *,
    provider_id: str,
    model: str,
    thinking_enabled: bool,
    tool_ids: dict[str, str],
) -> list[dict[str, Any]]:
    same_model = (
        message.provider == provider_id
        and message.api_type == "response"
        and message.model == model
    )
    output: list[dict[str, Any]] = []
    for block in message.content:
        if isinstance(block, ThinkingBlock):
            if not same_model or not thinking_enabled or not block.signature:
                continue
            try:
                reasoning = json.loads(block.signature)
            except ValueError:
                continue
            if isinstance(reasoning, dict):
                output.append(reasoning)
        elif isinstance(block, TextBlock):
            signature = _text_signature(block) if same_model else None
            if signature is not None:
                item: dict[str, Any] = {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": block.text,
                            "annotations": [],
                        }
                    ],
                    "status": "completed",
                }
                if isinstance(signature.get("id"), str):
                    item["id"] = signature["id"]
                if signature.get("phase") in {"commentary", "final_answer"}:
                    item["phase"] = signature["phase"]
                output.append(item)
            else:
                output.append({"role": "assistant", "content": block.text})
        elif isinstance(block, ToolCall):
            call_id = block.id if same_model else tool_ids.get(block.id, block.id)
            item = {
                "type": "function_call",
                "call_id": call_id,
                "name": block.name,
                "arguments": json.dumps(
                    block.arguments, ensure_ascii=False, separators=(",", ":")
                ),
            }
            if same_model and block.item_id is not None:
                item["id"] = block.item_id
            if same_model and block.namespace is not None:
                item["namespace"] = block.namespace
            output.append(item)
    return output


def _user_content(message: UserMessage) -> str | list[dict[str, Any]]:
    if isinstance(message.content, str):
        return message.content
    content: list[dict[str, Any]] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            content.append({"type": "input_text", "text": block.text})
        elif isinstance(block, ImageBlock):
            content.append(
                {
                    "type": "input_image",
                    "detail": "auto",
                    "image_url": f"data:{block.mime_type};base64,{block.data}",
                }
            )
    return content


def _convert_input(
    messages: list[TranscriptMessage],
    *,
    provider_id: str,
    model: str,
    thinking_enabled: bool,
) -> list[dict[str, Any]]:
    tool_ids = normalize_foreign_tool_ids(
        messages,
        provider_id=provider_id,
        api_type="response",
        model=model,
    )
    transcript: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, UserMessage):
            transcript.append({"role": "user", "content": _user_content(message)})
        elif isinstance(message, AssistantMessage):
            if message.stop_reason in {"error", "aborted"}:
                continue
            transcript.extend(
                _assistant_output(
                    message,
                    provider_id=provider_id,
                    model=model,
                    thinking_enabled=thinking_enabled,
                    tool_ids=tool_ids,
                )
            )
        elif isinstance(message, ToolResultMessage):
            transcript.append(
                {
                    "type": "function_call_output",
                    "call_id": tool_ids.get(message.tool_call_id, message.tool_call_id),
                    "output": _tool_output(message),
                }
            )
    return transcript


def _tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
            "strict": False,
        }
        for tool in tools
    ]


def _reasoning_text(item: object) -> str:
    parts: list[str] = []
    for entry in getattr(item, "summary", None) or []:
        text = getattr(entry, "text", None)
        if isinstance(text, str) and text:
            parts.append(text)
    for entry in getattr(item, "content", None) or []:
        text = getattr(entry, "text", None)
        if isinstance(text, str) and text:
            parts.append(text)
    return "\n\n".join(parts)


def _reasoning_signature(item: object) -> str | None:
    if hasattr(item, "model_dump"):
        data = cast(Any, item).model_dump(mode="json", exclude_none=True)
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return None


def _usage(usage: object) -> Usage:
    if usage is None:
        return Usage(0, 0, 0, 0)
    value = cast(Any, usage)
    input_tokens = int(getattr(value, "input_tokens", 0) or 0)
    details = getattr(value, "input_tokens_details", None)
    cached = int(getattr(details, "cached_tokens", 0) or 0) if details else 0
    return Usage(
        input_tokens=max(input_tokens - cached, 0),
        cache_creation_input_tokens=0,
        cache_read_input_tokens=cached,
        output_tokens=int(getattr(value, "output_tokens", 0) or 0),
    )


def _assistant_message(response: object, request: TurnRequest) -> AssistantMessage:
    content: list[TextBlock | ThinkingBlock | ToolCall] = []
    for item in cast(Any, response).output:
        item_type = getattr(item, "type", None)
        if item_type == "message":
            signature = None
            phase = getattr(item, "phase", None)
            item_id = getattr(item, "id", None)
            if item_id or phase:
                signature = json.dumps(
                    {
                        key: value
                        for key, value in {"id": item_id, "phase": phase}.items()
                        if value is not None
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            for part in getattr(item, "content", None) or []:
                part_type = getattr(part, "type", None)
                if part_type == "output_text":
                    content.append(
                        TextBlock(text=getattr(part, "text", ""), signature=signature)
                    )
                elif part_type == "refusal":
                    content.append(
                        TextBlock(
                            text=getattr(part, "refusal", ""), signature=signature
                        )
                    )
        elif item_type == "reasoning":
            content.append(
                ThinkingBlock(
                    thinking=_reasoning_text(item),
                    signature=_reasoning_signature(item),
                )
            )
        elif item_type == "function_call":
            try:
                arguments = json.loads(getattr(item, "arguments", "{}"))
            except ValueError:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            content.append(
                ToolCall(
                    id=str(getattr(item, "call_id", "")),
                    name=str(getattr(item, "name", "")),
                    arguments=arguments,
                    item_id=getattr(item, "id", None),
                    namespace=getattr(item, "namespace", None),
                )
            )
    stop_reason = (
        "tool_use"
        if any(isinstance(block, ToolCall) for block in content)
        else "end_turn"
    )
    return AssistantMessage(
        content=tuple(content),
        provider=request.provider.id,
        api_type="response",
        model=request.model,
        usage=_usage(getattr(response, "usage", None)),
        stop_reason=stop_reason,
        thinking_level=request.reasoning_effort,
    )


_SIWC_ERRORS = {
    "subscription_sharing_user_not_eligible": (
        "ChatGPT plan usage is not available for this account or workspace."
    ),
    "subscription_sharing_usage_limit_exceeded": (
        "A ChatGPT usage limit was reached. Check ChatGPT settings -> Usage."
    ),
    "subscription_sharing_usage_unavailable": (
        "ChatGPT usage could not be checked. Try again shortly."
    ),
    "subscription_sharing_unsupported_capability": (
        "This request uses a capability that ChatGPT plan usage does not support."
    ),
    "subscription_sharing_route_not_supported": (
        "This endpoint is not supported by ChatGPT plan usage."
    ),
    "subscription_sharing_invalid_user": (
        "ChatGPT could not validate this account. Run /login and try again."
    ),
    "subscription_sharing_user_unavailable": (
        "Your ChatGPT account is temporarily unavailable. Try again shortly."
    ),
    "chatpass_v2_scope_not_authorized": (
        "The ChatGPT grant does not authorize this request. Run /login again."
    ),
    "chatpass_v2_invalid_authorization_context": (
        "The ChatGPT authorization context is invalid. Run /login again."
    ),
}


def _error_from_event(event: object) -> ApiError:
    response = getattr(event, "response", None)
    error = getattr(response, "error", None) or getattr(event, "error", None)
    code = getattr(error, "code", None) or getattr(event, "code", None)
    message = getattr(error, "message", None) or "ChatGPT response failed"
    if isinstance(code, str) and code in _SIWC_ERRORS:
        message = _SIWC_ERRORS[code]
    return ApiError(str(message), code=str(code) if code else None)


class _ResponsesTurnStream(TurnStream):
    def __init__(self, request: TurnRequest) -> None:
        self._request = request
        self._manager: Any = None
        self._stream: Any = None

    def __enter__(self) -> _ResponsesTurnStream:
        reasoning, include, thinking_enabled = _reasoning_config(
            self._request.model,
            self._request.reasoning_effort,
            self._request.provider.auth_type,
        )
        kwargs: dict[str, Any] = {
            "model": self._request.model,
            "instructions": self._request.transcript.system,
            "input": _convert_input(
                self._request.transcript.messages,
                provider_id=self._request.provider.id,
                model=self._request.model,
                thinking_enabled=thinking_enabled,
            ),
            "store": False,
        }
        if self._request.transcript.tools:
            if self._request.provider.auth_type == "chatgpt":
                kwargs["input"] = [
                    {
                        "type": "additional_tools",
                        "role": "developer",
                        "tools": _tools(self._request.transcript.tools),
                    },
                    *kwargs["input"],
                ]
            else:
                kwargs["tools"] = _tools(self._request.transcript.tools)
        if self._request.session_id:
            kwargs["prompt_cache_key"] = self._request.session_id
        if (
            self._request.max_output_tokens
            and self._request.provider.auth_type != "chatgpt"
        ):
            kwargs["max_output_tokens"] = max(
                self._request.max_output_tokens, _MIN_OUTPUT_TOKENS
            )
        if reasoning is not None:
            kwargs["reasoning"] = reasoning
        if include is not None:
            kwargs["include"] = include
        client: OpenAI = get_responses_client()
        self._manager = client.responses.stream(**kwargs)
        self._stream = self._manager.__enter__()
        return self

    def __exit__(self, *args: object) -> None:
        if self._manager is not None:
            self._manager.__exit__(*args)

    def __iter__(self) -> Iterator[StreamEvent]:
        if self._stream is None:
            return
        for event in self._stream:
            event_type = getattr(event, "type", "")
            if event_type == "response.output_text.delta":
                yield NeutralTextDelta(str(getattr(event, "delta", "")))
            elif event_type in {
                "response.reasoning_summary_text.delta",
                "response.reasoning_text.delta",
            }:
                yield NeutralThinkingDelta(str(getattr(event, "delta", "")))
            elif event_type == "response.output_item.done":
                yield BlockEnd()
            elif event_type in {"response.failed", "response.incomplete", "error"}:
                raise _error_from_event(event)
            elif event_type == "response.completed":
                return

    def get_final_message(self) -> AssistantMessage:
        if self._stream is None:
            raise ApiError("Response stream was not opened")
        try:
            response = self._stream.get_final_response()
        except RuntimeError as exc:
            raise ApiError(str(exc)) from exc
        return _assistant_message(response, self._request)


class ResponsesBackend(ApiBackend):
    def run_turn(self, request: TurnRequest) -> TurnStream:
        return _ResponsesTurnStream(request)
