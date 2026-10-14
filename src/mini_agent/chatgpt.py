"""Synchronous Codex Responses transport with an Anthropic-shaped stream.

Only the transport is emulated: credentials are refreshed for every request and
history is sent explicitly (Codex requires ``store=False``). Codex reasoning is
carried in thinking signatures; function item IDs are extras on tool-use blocks,
so both survive the existing session serializer.
"""

# ruff: noqa: ANN401

import base64
import json
from collections.abc import Callable, Iterator
from types import TracebackType
from typing import Any, Self

import httpx
from anthropic.types import Message, RawMessageStreamEvent
from pydantic import TypeAdapter

from .oauth import Credentials, get_credentials

CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"
_SIGNATURE = "codex-reasoning:"
_EVENT = TypeAdapter(RawMessageStreamEvent)


class ChatGPTError(RuntimeError):
    """Safe transport/protocol error; never includes credentials or response bodies."""


def _dict(value: Any) -> dict[str, Any]:
    return (
        value.model_dump(exclude_none=True)
        if hasattr(value, "model_dump")
        else dict(value)
    )


def _content(content: Any, role: str) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [
            {
                "type": "output_text" if role == "assistant" else "input_text",
                "text": content,
            }
        ]
    result = []
    for raw in content:
        block = _dict(raw)
        if block["type"] == "text":
            result.extend(_content(block["text"], role))
        elif block["type"] == "image":
            source = block["source"]
            if source["type"] == "base64":
                url = f"data:{source['media_type']};base64,{source['data']}"
            elif source["type"] == "url":
                url = source["url"]
            else:
                raise ChatGPTError("Unsupported image source")
            result.append({"type": "input_image", "image_url": url, "detail": "auto"})
        else:
            raise ChatGPTError(f"Unsupported content block: {block['type']}")
    return result


def _input(messages: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in messages:
        role, content = message["role"], message["content"]
        if isinstance(content, str):
            result.append({"role": role, "content": _content(content, role)})
            continue
        pending: list[dict[str, Any]] = []

        def flush(pending: list[dict[str, Any]] = pending, role: str = role) -> None:
            if pending:
                result.append({"role": role, "content": list(pending)})
                pending.clear()

        for raw in content:
            block = _dict(raw)
            kind = block["type"]
            if kind in ("text", "image"):
                pending.extend(_content([block], role))
                continue
            flush()
            if kind == "tool_use":
                item = {
                    "type": "function_call",
                    "call_id": block["id"],
                    "name": block["name"],
                    "arguments": json.dumps(block["input"]),
                }
                if block.get("codex_item_id"):
                    item["id"] = block["codex_item_id"]
                result.append(item)
            elif kind == "tool_result":
                output = block.get("content", "")
                # Responses supports structured text/image function outputs.
                result.append(
                    {
                        "type": "function_call_output",
                        "call_id": block["tool_use_id"],
                        "output": output
                        if isinstance(output, str)
                        else _content(output, "user"),
                    }
                )
            elif kind == "thinking":
                signature = block.get("signature", "")
                if block.get("codex_reasoning"):
                    result.append(block["codex_reasoning"])
                elif signature.startswith(_SIGNATURE):
                    try:
                        item = json.loads(
                            base64.b64decode(
                                signature[len(_SIGNATURE) :], validate=True
                            )
                        )
                        if item.get("type") != "reasoning":
                            raise ValueError
                        result.append(item)
                    except (ValueError, TypeError, AttributeError) as exc:
                        raise ChatGPTError("Invalid saved Codex reasoning") from exc
                # Foreign provider reasoning cannot be replayed to Codex.
            elif kind != "redacted_thinking":
                raise ChatGPTError(f"Unsupported history block: {kind}")
        flush()
    return result


def _request(kwargs: dict[str, Any]) -> dict[str, Any]:
    system = kwargs.get("system", "")
    instructions = (
        system
        if isinstance(system, str)
        else "\n".join(_dict(b)["text"] for b in system)
    )
    body: dict[str, Any] = {
        "model": kwargs["model"],
        "instructions": instructions,
        "input": _input(kwargs["messages"]),
        "stream": True,
        "store": False,
        "include": ["reasoning.encrypted_content"],
    }
    if kwargs.get("tools"):
        body["tools"] = [
            {
                "type": "function",
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["input_schema"],
                "strict": False,
            }
            for t in map(_dict, kwargs["tools"])
        ]
    choice = kwargs.get("tool_choice")
    if choice:
        kind = choice["type"]
        body["tool_choice"] = (
            {"type": "function", "name": choice["name"]}
            if kind == "tool"
            else "required"
            if kind == "any"
            else kind
        )
    effort = (kwargs.get("output_config") or {}).get("effort", "medium")
    if (kwargs.get("thinking") or {}).get("type") != "disabled" and kwargs.get(
        "thinking"
    ):
        body["reasoning"] = {
            "effort": "xhigh" if effort == "max" else effort,
            "summary": "auto",
        }
    # max_tokens and cache_control are Anthropic settings unsupported by Codex.
    return body


def _blocks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks = []
    for item in items:
        kind = item["type"]
        if kind == "message":
            for part in item.get("content", []):
                if part["type"] in ("output_text", "refusal"):
                    blocks.append(
                        {
                            "type": "text",
                            "text": part.get("text", part.get("refusal", "")),
                        }
                    )
        elif kind == "function_call":
            try:
                arguments = json.loads(item.get("arguments", "{}"))
                if not isinstance(arguments, dict):
                    raise ValueError
            except (ValueError, TypeError) as exc:
                raise ChatGPTError("Codex returned invalid function arguments") from exc
            blocks.append(
                {
                    "type": "tool_use",
                    "id": item["call_id"],
                    "name": item["name"],
                    "input": arguments,
                    "codex_item_id": item.get("id"),
                }
            )
        elif kind == "reasoning":
            replay = {
                key: item[key]
                for key in ("type", "id", "summary", "encrypted_content")
                if key in item
            }
            signature = (
                _SIGNATURE + base64.b64encode(json.dumps(replay).encode()).decode()
            )
            blocks.append(
                {
                    "type": "thinking",
                    "thinking": "\n".join(
                        p.get("text", "") for p in item.get("summary", [])
                    ),
                    "signature": signature,
                    "codex_reasoning": replay,
                }
            )
    return blocks


class ChatGPTClient:
    """Use ``client.messages.stream(**anthropic_kwargs)`` with the existing loop.

    An injected HTTP client remains caller-owned. The default client is scoped
    to each stream. ``credentials`` is a zero-argument callback called on entry.
    """

    def __init__(
        self,
        *,
        http_client: httpx.Client | None = None,
        credentials: Callable[[], Credentials] | None = None,
    ) -> None:
        self.messages = self
        self._http_client = http_client
        self._credentials = credentials

    def stream(self, **kwargs: Any) -> ChatGPTStream:
        return ChatGPTStream(self, kwargs)


class ChatGPTStream:
    def __init__(self, client: ChatGPTClient, kwargs: dict[str, Any]) -> None:
        self._client = client
        self._kwargs = kwargs
        self._http: httpx.Client | None = None
        self._response: httpx.Response | None = None
        self._iterator: Iterator[RawMessageStreamEvent] | None = None
        self._final: Message | None = None

    def __enter__(self) -> Self:
        body = _request(self._kwargs)
        credentials = (self._client._credentials or get_credentials)()
        self._http = self._client._http_client or httpx.Client(
            timeout=httpx.Timeout(300, connect=30)
        )
        try:
            request = self._http.build_request(
                "POST",
                CODEX_URL,
                json=body,
                headers={
                    "Authorization": f"Bearer {credentials.access_token}",
                    "ChatGPT-Account-Id": credentials.account_id,
                    "Accept": "text/event-stream",
                },
            )
            self._response = self._http.send(request, stream=True)
            if self._response.status_code >= 400:
                raise ChatGPTError(f"Codex HTTP error {self._response.status_code}")
            if "text/event-stream" not in self._response.headers.get(
                "content-type", ""
            ):
                raise ChatGPTError("Codex returned a non-SSE response")
            self._iterator = self._events()
            return self
        except httpx.HTTPError:
            self.close()
            raise ChatGPTError("Codex connection failed") from None
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self._response is not None:
            self._response.close()
        if self._http is not None and self._client._http_client is None:
            self._http.close()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> RawMessageStreamEvent:
        if self._iterator is None:
            raise RuntimeError("Enter the stream context before iterating")
        return next(self._iterator)

    def get_final_message(self) -> Message:
        for _ in self:
            pass
        if self._final is None:
            raise ChatGPTError("Codex stream ended without a completed response")
        return self._final

    def _sse(self) -> Iterator[dict[str, Any]]:
        data: list[str] = []
        assert self._response is not None
        for line in self._response.iter_lines():
            if not line:
                if data:
                    payload = "\n".join(data)
                    data.clear()
                    if payload == "[DONE]":
                        return
                    try:
                        event = json.loads(payload)
                        if not isinstance(event, dict):
                            raise ValueError
                    except ValueError:
                        raise ChatGPTError(
                            "Codex returned malformed SSE data"
                        ) from None
                    yield event
            elif line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
        if data:
            raise ChatGPTError("Codex stream ended with an unterminated SSE event")

    def _events(self) -> Iterator[RawMessageStreamEvent]:
        def event(kind: str, **fields: Any) -> RawMessageStreamEvent:
            return _EVENT.validate_python({"type": kind, **fields})

        active: dict[tuple[int, str, int], int] = {}
        texts: dict[tuple[int, str, int], str] = {}
        next_index = 0
        closed: set[tuple[int, str, int]] = set()
        summary_parts: dict[int, int] = {}

        def start(
            key: tuple[int, str, int], block: dict[str, Any]
        ) -> Iterator[RawMessageStreamEvent]:
            nonlocal next_index
            if key not in active:
                active[key] = next_index
                next_index += 1
                texts[key] = ""
                yield event(
                    "content_block_start", index=active[key], content_block=block
                )

        def finish(index: int, item: dict[str, Any]) -> Iterator[RawMessageStreamEvent]:
            for part, block in enumerate(_blocks([item])):
                category = "tool" if block["type"] == "tool_use" else block["type"]
                key = (index, category, part)
                if key in closed:
                    continue
                initial = dict(block)
                if category == "tool":
                    initial["input"] = {}
                    value = item.get("arguments", "{}")
                    delta_type, delta_field = "input_json_delta", "partial_json"
                else:
                    initial[category] = ""
                    value = block[category]
                    delta_type, delta_field = f"{category}_delta", category
                yield from start(key, initial)
                # Done events are authoritative; fill content omitted by proxies.
                previous = texts[key]
                if value.startswith(previous) and value[len(previous) :]:
                    yield event(
                        "content_block_delta",
                        index=active[key],
                        delta={"type": delta_type, delta_field: value[len(previous) :]},
                    )
                if category == "thinking" and key not in closed:
                    yield event(
                        "content_block_delta",
                        index=active[key],
                        delta={
                            "type": "signature_delta",
                            "signature": block["signature"],
                        },
                    )
                if key not in closed:
                    closed.add(key)
                    yield event("content_block_stop", index=active[key])

        items: dict[int, dict[str, Any]] = {}
        try:
            yield event(
                "message_start",
                message={
                    "id": "codex",
                    "type": "message",
                    "role": "assistant",
                    "model": self._kwargs["model"],
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            )
            for data in self._sse():
                kind = data.get("type", "")
                index = data.get("output_index", 0)
                if kind == "response.output_item.added":
                    items[index] = data["item"]
                    item = data["item"]
                    if item["type"] == "function_call":
                        yield from start(
                            (index, "tool", 0),
                            {
                                "type": "tool_use",
                                "id": item["call_id"],
                                "name": item["name"],
                                "input": {},
                                "codex_item_id": item.get("id"),
                            },
                        )
                elif kind in (
                    "response.output_text.delta",
                    "response.refusal.delta",
                    "response.reasoning_summary_text.delta",
                    "response.function_call_arguments.delta",
                ):
                    category = (
                        "tool"
                        if "arguments" in kind
                        else "thinking"
                        if "reasoning" in kind
                        else "text"
                    )
                    part = (
                        data.get("summary_index", data.get("content_index", 0))
                        if category == "text"
                        else 0
                    )
                    key = (index, category, part)
                    if category == "tool":
                        item = items.get(index, {})
                        block = {
                            "type": "tool_use",
                            "id": item.get("call_id", data.get("item_id", "")),
                            "name": item.get("name", ""),
                            "input": {},
                        }
                    else:
                        block = {"type": category, category: ""}
                        if category == "thinking":
                            block["signature"] = ""
                    yield from start(key, block)
                    delta = data["delta"]
                    if category == "thinking":
                        summary_index = data.get("summary_index", 0)
                        if (
                            index in summary_parts
                            and summary_parts[index] != summary_index
                        ):
                            delta = "\n" + delta
                        summary_parts[index] = summary_index
                    texts[key] += delta
                    delta_block = (
                        {"type": "input_json_delta", "partial_json": delta}
                        if category == "tool"
                        else {"type": f"{category}_delta", category: delta}
                    )
                    yield event(
                        "content_block_delta", index=active[key], delta=delta_block
                    )
                elif kind == "response.output_item.done":
                    items[index] = data["item"]
                    yield from finish(index, data["item"])
                elif kind in ("response.failed", "response.incomplete", "error"):
                    raise ChatGPTError(f"Codex stream reported {kind}")
                elif kind == "response.completed":
                    response = data["response"]
                    if response.get("status", "completed") != "completed":
                        raise ChatGPTError("Codex response did not complete")
                    output = response.get("output", [items[i] for i in sorted(items)])
                    blocks = _blocks(output)
                    for item_index, item in enumerate(output):
                        yield from finish(item_index, item)
                    for key, block_index in active.items():
                        if key not in closed:
                            closed.add(key)
                            yield event("content_block_stop", index=block_index)
                    usage = response.get("usage") or {}
                    cached = (usage.get("input_tokens_details") or {}).get(
                        "cached_tokens", 0
                    )
                    input_tokens = usage.get("input_tokens", 0)
                    stop = (
                        "tool_use"
                        if any(b["type"] == "tool_use" for b in blocks)
                        else "end_turn"
                    )
                    mapped_usage = {
                        "input_tokens": max(0, input_tokens - cached),
                        "cache_read_input_tokens": cached,
                        "output_tokens": usage.get("output_tokens", 0),
                    }
                    self._final = Message.model_validate(
                        {
                            "id": response.get("id", "codex"),
                            "type": "message",
                            "role": "assistant",
                            "model": response.get("model", self._kwargs["model"]),
                            "content": blocks,
                            "stop_reason": stop,
                            "stop_sequence": None,
                            "usage": mapped_usage,
                        }
                    )
                    yield event(
                        "message_delta",
                        delta={"stop_reason": stop, "stop_sequence": None},
                        usage=mapped_usage,
                    )
                    yield event("message_stop")
                    return
            raise ChatGPTError("Codex stream ended without a completed response")
        except httpx.HTTPError:
            raise ChatGPTError("Codex stream connection failed") from None
        except KeyError, TypeError, ValueError:
            raise ChatGPTError("Codex returned an invalid stream event") from None
        finally:
            self.close()
