# Plan: provider `api_type` and ChatGPT OAuth in two PRs

Based on [`docs/research/sign-in-with-chatgpt.md`](../research/sign-in-with-chatgpt.md)
and the provider/context design in Pi (`/Users/kowyo/Documents/pi`,
especially `packages/ai/src/api/transform-messages.ts`,
`openai-responses-shared.ts`, `anthropic-messages.ts`, and
`packages/ai/src/types.ts`).

## Goal

Make mini-agent protocol-agnostic:

- **PR 1** adds `api_type` to providers with two values, `"message"` and
  `"response"`. A provider is then just `(base_url, credentials, api_type)`;
  the agent loop no longer depends on Anthropic request/response types.
- **PR 2** adds ChatGPT OAuth (`/login`, `/logout`) on top of the `"response"`
  backend. It reuses PR 1 rather than introducing a second agent loop.

No user documentation updates are part of either PR. Session backward
compatibility is intentionally dropped.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Canonical transcript | Provider-neutral dataclasses (`TextBlock`, `ThinkingBlock`, `ImageBlock`, `ToolCall`, `UserMessage`, `AssistantMessage`, `ToolResultMessage`) | Provider-agnostic agent loop; makes cross-provider handoff explicit instead of smuggling Responses data through Anthropic blocks |
| `api_type` location | Provider config field, default `"message"` | Matches the request; existing providers keep working without new config |
| Supported values | `"message"` (Anthropic Messages), `"response"` (OpenAI Responses) | Exact names requested; reject anything else at config load |
| Backend seam | `run_turn(TurnRequest) -> TurnStream`; two adapters | Small interface: one call, one stream, one final message. `agent_loop` keeps tool execution, interrupts, and session flow |
| Session format | Version 2 JSONL, neutral messages, per-assistant `provider` / `api_type` / `model` | Assistant metadata is required to decide whether provider-native thinking can be replayed |
| Old sessions | Skip version 1 files; no migration | Explicitly allowed by the request |
| Cache control | Never stored in the transcript; applied per request by each adapter | Prevents stale Anthropic markers leaking into Responses and vice versa |
| Thinking replay | Replay only when provider + api_type + model match and thinking is enabled for the current request; otherwise drop at request time, keep in storage | Follows Pi; switching back to the original model can reuse the stored blocks |
| Provider switching | Preserve text, images, tool calls, tool results; drop foreign thinking and provider-native IDs; normalize tool IDs | Matches Pi's cross-provider handoff rules |
| Responses tool shape (PR 1) | Top-level `tools` | Standard Responses API shape for API-key providers |
| Responses tool shape (PR 2) | `additional_tools` input item for ChatGPT plan usage | Required by the SIWC preview contract |
| Responses caching | `prompt_cache_key = session_id` when `cache_control` is enabled; no retention/options fields | Stable per session; avoids fields the ChatGPT route rejects |
| Reasoning support | Use models.dev `reasoning` / `reasoning_options` when known; omit `reasoning` when unsupported or unknown | Avoids sending `reasoning` to non-reasoning Responses models |
| Dependencies | PR 1: `openai`; PR 2: `PyJWT[crypto]` (and `filelock` if used) | Keeps OAuth dependencies out of PR 1 |
| PR sequencing | PR 1 merges first; PR 2 rebases on the merged PR 1 | PR 2 consumes the backend/seam; avoids a long-lived stacked branch |

### Explicit non-goals

- No Pi-style `configuration_update` effort markers in PR 1. Changing effort
  mid-session may invalidate a provider prompt cache; that is accepted. The
  important guarantee is that incompatible thinking is never replayed.
- No multi-account ChatGPT support in PR 2.
- No Codex app-server or unofficial Codex OAuth.
- No hosted Responses tools, file search, Code Interpreter, or computer use.
- No session migration.
- No user docs updates.

---

# PR 1 — `api_type` and the Responses backend

## 1. Neutral transcript module

New `src/mini_agent/agent/transcript.py`:

```python
ApiType = Literal["message", "response"]

@dataclass(frozen=True)
class TextBlock:
    text: str
    signature: str | None = None      # Responses message id/phase, stored as JSON

@dataclass(frozen=True)
class ThinkingBlock:
    thinking: str
    signature: str | None = None      # Anthropic signature or Responses reasoning item JSON
    redacted: bool = False

@dataclass(frozen=True)
class ImageBlock:
    data: str                         # base64
    mime_type: str

@dataclass(frozen=True)
class ToolCall:
    id: str                           # provider call id
    name: str
    arguments: dict[str, Any]
    item_id: str | None = None        # Responses function_call item id
    namespace: str | None = None      # Responses namespace, if any

@dataclass(frozen=True)
class UserMessage:
    content: str | tuple[TextBlock | ImageBlock, ...]

@dataclass(frozen=True)
class AssistantMessage:
    content: tuple[TextBlock | ThinkingBlock | ToolCall, ...]
    provider: str
    api_type: ApiType
    model: str
    usage: Usage
    stop_reason: str
    thinking_level: str | None = None

@dataclass(frozen=True)
class ToolResultMessage:
    tool_call_id: str
    name: str
    content: tuple[TextBlock | ImageBlock, ...]
    is_error: bool = False

Message = UserMessage | AssistantMessage | ToolResultMessage

@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]

@dataclass
class Transcript:
    system: str
    tools: list[ToolSpec]
    messages: list[Message]
```

Design notes:

- Tool results become their own messages. Anthropic groups consecutive
  tool-result messages into one user message with `tool_result` blocks;
  Responses emits one `function_call_output` item per result. This is the key
  shape change that makes cross-provider handoff clean.
- `ThinkingBlock.signature` is opaque. For Anthropic it is the thinking
  signature or redacted payload. For Responses it is the JSON of the
  `reasoning` output item, including `encrypted_content` when available.
- `TextBlock.signature` is only used by Responses to replay assistant message
  `id` and `phase` for the same model.
- `ToolCall.item_id` / `namespace` are Responses-only replay data. They are
  ignored when converting to Anthropic and when the target model differs.
- `Usage` stays in `src/mini_agent/cli/token.py`; adapters import it.

Add `to_dict` / `from_dict` helpers for session JSON. Serialized shapes:

```json
{"type": "text", "text": "..."}
{"type": "thinking", "thinking": "...", "signature": "...", "redacted": false}
{"type": "image", "data": "...", "mime_type": "image/png"}
{"type": "tool_call", "id": "call_1", "name": "bash", "arguments": {"command": "ls"}, "item_id": null, "namespace": null}
{"role": "user", "content": "..."}
{"role": "assistant", "content": [...], "provider": "openai", "api_type": "response", "model": "gpt-5.4", "usage": {...}, "stop_reason": "tool_use", "thinking_level": "high"}
{"role": "tool_result", "tool_call_id": "call_1", "name": "bash", "content": [...], "is_error": false}
```

## 2. Provider config

`src/mini_agent/config.py`:

- `Provider` gains `api_type: ApiType = "message"`.
- `Provider.api_key_env` becomes `str | None = None` (PR 2 will use `None` for
  the ChatGPT provider).
- `get_providers()` reads `api_type` from the provider table, defaults to
  `"message"`, and rejects values other than `"message"` / `"response"`.
- `get_provider()` and client caching work unchanged; `Provider` stays frozen
  and hashable.
- Add `get_api_key(provider) -> str` (PR 1: read `api_key_env`; PR 2 extends
  it for ChatGPT credentials).

Config shape:

```toml
provider = "openai"
model_id = "gpt-5.4"
reasoning_effort = "high"
cache_control = true

[providers.openai]
name = "OpenAI"
api_type = "response"
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"

[providers.anthropic]
name = "Anthropic"
api_type = "message"
base_url = "https://api.anthropic.com"
api_key_env = "ANTHROPIC_API_KEY"
```

## 3. Backend seam

New `src/mini_agent/agent/api/`:

```text
api/__init__.py       # get_backend(provider) -> ApiBackend
api/base.py           # TurnRequest, StreamEvent, TurnStream protocol
api/message.py        # Anthropic Messages adapter
api/response.py       # OpenAI Responses adapter
```

```python
@dataclass
class TurnRequest:
    transcript: Transcript
    provider: Provider
    model: str
    reasoning_effort: str
    cache_control: bool
    session_id: str | None
    max_output_tokens: int | None

@dataclass(frozen=True)
class TextDelta:
    text: str

@dataclass(frozen=True)
class ThinkingDelta:
    text: str

@dataclass(frozen=True)
class BlockEnd:
    pass

StreamEvent = TextDelta | ThinkingDelta | BlockEnd

class TurnStream(Protocol):
    def __enter__(self) -> TurnStream: ...
    def __exit__(self, *args: object) -> None: ...
    def __iter__(self) -> Iterator[StreamEvent]: ...
    def get_final_message(self) -> AssistantMessage: ...

class ApiBackend(Protocol):
    def run_turn(self, request: TurnRequest) -> TurnStream: ...
```

`get_backend(provider)` selects by `provider.api_type`. This is the only
protocol switch in the application.

`agent_loop` changes:

- Accept a `Transcript` instead of `list[MessageParam]`.
- Build a `TurnRequest` from the transcript and current config.
- Keep the existing status lifecycle, `with backend.run_turn(...)`, display,
  tool execution, interrupt back-fill, and "discard incomplete turn" behavior.
- Append the returned `AssistantMessage`; if it has tool calls, execute them
  and append one `ToolResultMessage` per call; continue while any tool call was
  returned.
- `cache_control` and `reasoning_effort` are read from config at request time.

## 4. Anthropic Messages adapter (`api/message.py`)

Request conversion:

- System prompt → `system` (current `SYSTEM`).
- `ToolSpec` → `{name, description, input_schema: parameters}`.
- Messages:
  - `UserMessage` text/images → Anthropic user content blocks.
  - `AssistantMessage` text/thinking/tool calls → Anthropic assistant content
    blocks.
  - Consecutive `ToolResultMessage`s → one user message with `tool_result`
    blocks; `is_error` maps directly.
- Thinking replay rule:
  - Replay a `ThinkingBlock` only if
    `message.provider == provider.id and message.api_type == "message" and
    message.model == model` and current effort is not `"disabled"`.
  - Otherwise drop it from the request (do not delete it from the transcript).
  - `redacted` thinking maps to Anthropic `redacted_thinking` with `data =
    signature`.
- Tool call IDs:
  - Normalize to `^[A-Za-z0-9_-]{1,64}$` for the target request.
  - Rewrite matching `ToolResultMessage.tool_call_id` through the same map.
  - Preserve original IDs in the transcript.
- Defensive cleanup for resumed/foreign transcripts:
  - Skip `AssistantMessage`s with `stop_reason` `"error"` or `"aborted"`.
  - Insert a synthetic "No result provided" tool result for orphaned calls.
  - If an error tool result contains images, keep the text in the
    `tool_result` and place the images after the tool results in the same user
    message (Anthropic rejects images inside error results).
- Request parameters:
  - `max_tokens` = existing output limit or 32768.
  - `thinking` / `output_config` = existing logic from
    `agent/agent.py:37-46`.
  - `cache_control` = existing top-level parameter when config enables it.
  - No cache markers in transcript or session.

Response conversion:

- Anthropic `TextBlock` → neutral `TextBlock`.
- `ThinkingBlock` → neutral `ThinkingBlock(signature=block.signature)`.
- `RedactedThinkingBlock` → neutral `ThinkingBlock(redacted=True,
  signature=block.data)`.
- `ToolUseBlock` → neutral `ToolCall(id=block.id, name=block.name,
  arguments=block.input)`.
- Usage mapping unchanged (input / cache creation / cache read / output).
- `stop_reason`: `tool_use`, `end_turn`, `max_tokens`, or the raw value.
- Set `provider`, `api_type="message"`, `model`, and `thinking_level` from the
  request.

Streaming:

- `content_block_delta` `TextDelta` → neutral `TextDelta`.
- `ThinkingDelta` → neutral `ThinkingDelta`.
- `content_block_stop` → neutral `BlockEnd`.
- Shared `display_stream_events` consumes neutral events; the Rich `Live`
  rendering code is reused, not duplicated.

## 5. OpenAI Responses adapter (`api/response.py`)

Request conversion:

- System prompt → `instructions`.
- `ToolSpec` → `{type: "function", name, description, parameters, strict:
  false}`.
- PR 1 sends tools in top-level `tools`. PR 2 adds an `additional_tools` mode
  for ChatGPT plan usage.
- Messages:
  - `UserMessage` text → `{role: "user", content: text}`.
  - `UserMessage` images → `input_text` / `input_image` content items with data
    URLs.
  - Assistant same model:
    - text with a signature → a `message` item with `id` / `phase` from the
      signature, `content: [{type: "output_text", ...}]`.
    - text without a signature → a plain assistant message.
    - `ThinkingBlock` with a signature → the stored `reasoning` item JSON.
    - `ToolCall` → `function_call` with `call_id`, `name`, `arguments`,
      `item_id` when same model, and `namespace` when present.
  - Assistant different model/provider/api:
    - drop thinking;
    - plain assistant text;
    - `function_call` without `item_id`/`namespace`;
    - normalize foreign call IDs.
  - `ToolResultMessage` → `function_call_output` with `call_id` and
    `output` (string or `input_text`/`input_image` list); `is_error` prefixes
    `"Error: "`.
- Reasoning:
  - Use models.dev `reasoning` when known. Omit `reasoning` when unsupported or
    unknown.
  - Map effort: `disabled` → `"none"`, `adaptive` → omit, `low`/`medium`/
    `high`/`xhigh`/`max` → pass through when the model catalog lists them.
  - When reasoning is enabled, request
    `include=["reasoning.encrypted_content"]` so the reasoning item can be
    replayed.
- Cache:
  - When `cache_control` is enabled and `session_id` is available, send
    `prompt_cache_key=session_id`.
  - Do not send `prompt_cache_retention` or `prompt_cache_options`.
  - No cache state in the transcript.
- Request parameters:
  - `store=False`, streaming via `client.responses.stream(...)`.
  - `max_output_tokens` from the existing output limit for generic Responses
    providers. PR 2 omits it for ChatGPT plan usage.
  - No `temperature`, `top_p`, `truncation`, `user`, `metadata`, or other
    unsupported fields.

Response conversion:

- `message` output item → neutral `TextBlock` with
  `signature=json.dumps({"id": item.id, "phase": item.phase})` when present.
- `reasoning` output item → neutral `ThinkingBlock` with
  `thinking=` its summary/content text and `signature=json.dumps(item)`.
- `function_call` output item → neutral `ToolCall(id=call_id, name,
  arguments=json.loads(arguments), item_id=id, namespace=namespace)`.
- `stop_reason`: `"tool_use"` if any function call, otherwise `"end_turn"`.
- Usage:
  - `output_tokens` → `Usage.output_tokens`.
  - `input_tokens - input_tokens_details.cached_tokens` → `Usage.input_tokens`.
  - `cached_tokens` → `Usage.cache_read_input_tokens`.
  - `cache_creation_input_tokens = 0`.
- `provider`, `api_type="response"`, `model`, `thinking_level` set from the
  request.

Streaming and failures:

- `response.output_text.delta` → neutral `TextDelta`.
- `response.reasoning_summary_text.delta` / `response.reasoning_text.delta` →
  neutral `ThinkingDelta`.
- `response.output_item.done` / content-part done → neutral `BlockEnd`.
- Inspect `response.failed`, `response.incomplete`, and `error` events before
  calling `get_final_response()`. The Python SDK's `get_final_response()`
  raises a generic `RuntimeError` when `response.completed` never arrives, so
  the adapter must surface the real error code first.
- Treat a stream that ends without `response.completed` as failure.

## 6. Tool and image migration

Neutralize the existing tool pipeline:

- `agent/tools/schemas.py`: `TOOLS: list[ToolSpec]` using `parameters` instead
  of `input_schema`.
- `agent/tools/file.py`: return neutral `TextBlock` / `ImageBlock`.
- `agent/tools/base.py`: `ToolError.content` uses neutral blocks.
- `agent/mcp/tools.py`: build `ToolSpec`; map MCP text/image results to neutral
  blocks.
- `agent/system_prompt.py`: `TOOLS_LIST` reads `tool.name` / `tool.description`.
- `cli/clipboard.py`: `create_image_content()` returns `ImageBlock`;
  `extract_text_content()` reads neutral blocks.
- `cli/image_messages.py`: count/build neutral image blocks.
- `cli/display/printing.py`: render neutral blocks; `_split_tool_output`
  handles neutral `ImageBlock`.
- `cli/display/stream.py`: consume neutral `TextDelta` / `ThinkingDelta` /
  `BlockEnd`.

## 7. Session storage version 2

`src/mini_agent/cli/sessions.py`:

- `SessionManager.VERSION = 2`.
- `StoredSession.history: list[Message]`.
- Save each neutral message with `to_dict`; assistant entries include
  `provider`, `api_type`, `model`, `usage`, `stop_reason`, `thinking_level`.
- Derive `round_usages` from assistant entries on load; remove the duplicate
  `round_usages` argument from `save` (call sites updated).
- Version 1 files are skipped by `list_sessions` and `load`. No migration.
- `session_title` reads neutral user text.
- `serialize_content` is removed.
- Thinking signatures, encrypted reasoning JSON, images, and tool metadata
  persist exactly; cache control does not.

Why this matters:

- The current session format writes `model = config.get_model()` at save time,
  which is wrong after a provider/model switch. Per-assistant metadata fixes it.
- Cross-provider resume works because each assistant message says what produced
  it, so the target adapter can decide whether to replay its thinking.

## 8. Model listing

`src/mini_agent/cli/models.py`:

- Branch on `config.get_provider().api_type`.
- `message`: keep the existing Anthropic SDK / manual `/v1/models` path.
- `response`: use the OpenAI SDK `client.models.list()` (`data[].id`), with the
  existing manual fallback for OpenAI-shaped `/models` responses.
- Extend `_flatten_catalog` to retain `reasoning` and `reasoning_options`
  alongside `limit`; expose `get_model_reasoning(model_id)` and
  `get_reasoning_efforts(model_id)`. The Responses adapter uses these to decide
  whether to send `reasoning` and which effort values are valid. If the model is
  unknown, omit `reasoning`.
- `get_max_output_tokens` / `get_max_context_tokens` stay as-is.
- PR 2 adds the ChatGPT custom catalog shape (`.models[]`, `visibility`,
  `slug`).

## 9. Files touched (PR 1)

| File | Change |
|---|---|
| `pyproject.toml` | Add `openai` |
| `src/mini_agent/agent/transcript.py` | New neutral message/tool types + JSON helpers |
| `src/mini_agent/agent/api/base.py` | `TurnRequest`, stream events, protocols |
| `src/mini_agent/agent/api/message.py` | Anthropic adapter |
| `src/mini_agent/agent/api/response.py` | Responses adapter |
| `src/mini_agent/agent/api/__init__.py` | `get_backend(provider)` |
| `src/mini_agent/agent/agent.py` | Transcript-driven shared loop; backend seam |
| `src/mini_agent/agent/tools/schemas.py` | Neutral `ToolSpec` |
| `src/mini_agent/agent/tools/file.py` | Neutral image/text results |
| `src/mini_agent/agent/tools/base.py` | Neutral `ToolError` content |
| `src/mini_agent/agent/tools/handlers.py` | Type-only changes |
| `src/mini_agent/agent/mcp/tools.py` | Neutral tool/result mapping |
| `src/mini_agent/agent/system_prompt.py` | Neutral tool list |
| `src/mini_agent/config.py` | `api_type`, optional `api_key_env`, `get_api_key` |
| `src/mini_agent/cli/sessions.py` | Version 2 neutral session storage |
| `src/mini_agent/cli/main.py` | `Transcript` construction; pass session id |
| `src/mini_agent/cli/prompt_session.py` | Neutral image/history types |
| `src/mini_agent/cli/image_messages.py` | Neutral image blocks |
| `src/mini_agent/cli/clipboard.py` | Neutral image/text blocks |
| `src/mini_agent/cli/display/stream.py` | Neutral stream events |
| `src/mini_agent/cli/display/printing.py` | Neutral message rendering |
| `src/mini_agent/cli/models.py` | Model listing branch; retain `reasoning` metadata |
| `tests/…` | Update Anthropic tests; add adapter/session/translation tests |

## 10. PR 1 tests

- Transcript JSON round-trip: text, thinking signatures, redacted thinking,
  images, tool calls with item IDs/namespaces, tool results, assistant
  metadata, usage.
- Session version 2: save/load, title, round usage derivation, old version
  skipped.
- Anthropic adapter:
  - text/image/tool conversion both ways;
  - thinking replay for same model + enabled thinking;
  - thinking dropped for different model, different api_type, or disabled;
  - redacted thinking replay;
  - tool-call ID normalization and tool-result rewriting;
  - orphaned tool calls get synthetic results;
  - cache_control is applied to the request and absent from session JSON.
- Responses adapter:
  - top-level tools shape;
  - user/assistant/tool-result input items;
  - same-model text/reasoning/function-call replay;
  - foreign-model thinking dropped, item IDs/namespaces dropped;
  - `store=False`, streaming, `prompt_cache_key` behavior;
  - `max_output_tokens` presence for generic providers;
  - usage mapping including cached tokens;
  - `response.failed` / `response.incomplete` / missing `response.completed`.
- Cross-provider handoff:
  - Anthropic → Responses → Anthropic;
  - Responses → Anthropic → Responses;
  - text, images, tool calls, tool results, and tool-call IDs remain coherent.
- Agent loop:
  - backend selection by `api_type`;
  - tool execution and interrupt back-fill unchanged;
  - incomplete turn discarded on error.
- Config:
  - default `api_type="message"`;
  - valid `"response"`;
  - invalid value rejected;
  - missing API key reported.

Use fake SDK streams for unit tests. Optionally add one offline integration test
that runs the Responses adapter against a local HTTP stub returning a synthetic
SSE stream (no live credentials).

## 11. PR 1 commit sequence

1. `refactor(agent): introduce neutral transcript types`
2. `refactor(agent): isolate anthropic messages behind a backend seam`
3. `feat(providers): add api_type and response api backend`
4. `refactor(session): persist neutral transcripts as version 2`
5. `refactor(cli): render neutral messages and tool results`
6. `test(agent): cover adapters, cross-provider handoff, and session storage`

Each commit should keep `make check` green.

---

# PR 2 — ChatGPT OAuth on the Responses backend

PR 2 assumes PR 1 is merged. It must not change the neutral transcript model.
The agent loop may gain a small capability value on `TurnRequest`, but its
control flow stays the same.

## 1. Provider and auth seam

- `Provider` gains `auth_type: Literal["api_key", "chatgpt"] = "api_key"`.
- Built-in provider:

```python
Provider(
    id="chatgpt",
    name="ChatGPT",
    api_type="response",
    base_url="https://api.openai.com/v1",
    api_key_env=None,
    auth_type="chatgpt",
)
```

- `get_api_key(provider)`:
  - `api_key` → read the env var;
  - `chatgpt` → return a valid OAuth access token, refreshing if needed.
- The built-in ChatGPT provider always appears in `get_providers()` so
  `mini` works without a `config.toml`. It is selectable with `/provider` or
  `--provider chatgpt`.
- If ChatGPT is selected without credentials, print a "run /login" hint instead
  of failing with a missing env var.

## 2. OAuth module

New `src/mini_agent/chatgpt/`:

```text
auth.py          # discovery, PKCE, loopback callback, token exchange, refresh, revoke
credentials.py   # load/save/validate, 0600, atomic write, refresh lock
```

Follow the official OSS flow in the research document:

- stable host ID at `~/.mini-agent/chatgpt-host.json`;
- dynamic registration with `client_id=dynamic_agent_client`,
  `agent_name_hint=mini-agent`, `ext_agent_host_id`;
- loopback listener on `127.0.0.1`, path `/auth/callback`, fresh state/nonce/
  PKCE per attempt;
- token exchange with the issued client ID;
- ID-token verification against OpenAI JWKS (`PyJWT[crypto]`);
- credential record at `~/.mini-agent/chatgpt.json`, atomic `0600`;
- refresh with rotating token under a lock;
- revocation on logout, retaining registration and host ID.

For the known refresh-token failure, the fallback is: clear unusable tokens,
report that the session expired, and ask the user to run `/login`. Do not
silently retry OAuth.

## 3. `/login` and `/logout`

`src/mini_agent/cli/main.py` and `cli/display/completion.py`:

- `/login`: run the browser flow, save credentials, set the session provider to
  `chatgpt`, and report the account. If the current model is not in the fetched
  catalog, open the model picker (or instruct the user to run `/model`).
- `/logout`: revoke the renewable session, clear local tokens, and switch to the
  first non-ChatGPT provider if one exists; otherwise leave `chatgpt` selected
  with a "signed out" status.
- Both commands are available even when the active provider is not ChatGPT.
- No `mini login` subcommand is required; the requested surface is the slash
  commands.

## 4. ChatGPT-specific Responses behavior

Add a small capability layer, not a second backend:

| Capability | Generic `response` (PR 1) | ChatGPT plan usage (PR 2) |
|---|---|---|
| Tools | top-level `tools` | `additional_tools` input item |
| `max_output_tokens` | send when known | omit |
| `prompt_cache_key` | send when caching enabled | send when caching enabled |
| `prompt_cache_retention` / `prompt_cache_options` | omit | omit |
| Model catalog | OpenAI `data[].id` | `.models[]` with `visibility` / `slug` |
| Reasoning | per model catalog | send when enabled; verify `include` support in the spike |
| Errors | generic SDK errors | map SIWC codes to actionable messages |

The Responses adapter can read these from the `Provider` (`auth_type`) or from
a small `ResponsesCapabilities` value passed in `TurnRequest`. Keep it to the
few flags above.

## 5. PR 2 tests

- OAuth URL builder: PKCE S256, state/nonce, scope, resource, host ID,
  `agent_name_hint` only on first registration.
- Callback: state mismatch, duplicate parameters, wrong host/path,
  `error=access_denied`, missing issued client ID.
- Token exchange/refresh/revoke request bodies; rotated refresh token persisted
  before use.
- ID-token validation with a generated RSA key and local JWKS.
- Credential store: atomic write, `0600`, corrupt-file handling, refresh lock.
- ChatGPT Responses behavior: `additional_tools` shape, omitted
  `max_output_tokens`, `prompt_cache_key`, custom model catalog parsing, SIWC
  error mapping.
- `/login` / `/logout` dispatch and provider switching.

All tests use mocked HTTP. A live spike is still required for refresh and the
exact tool shape.

---

# Cross-cutting invariants

1. **One transcript, two wire formats.** Session files and the agent loop see
   only neutral messages. Provider-native IDs/signatures are opaque metadata.
2. **Cache state is not history.** `cache_control`, `prompt_cache_key`, and
   retention settings are request-time only; they never enter a session file or
   another provider's request.
3. **Thinking replay is model-bound.** A thinking/reasoning block is replayed
   only when provider + `api_type` + model match and thinking is enabled for the
   current request. It is kept in storage so switching back can reuse it.
4. **Text, images, tools, and results survive switches.** Only provider-native
   thinking and IDs are dropped or normalized.
5. **Tool IDs are request-local.** Normalization never mutates the stored
   transcript.
6. **No backward compatibility.** Version 1 sessions are ignored, not migrated.
7. **Two adapters justify the seam.** `message` and `response` are the only
   implementations; no provider registry or plugin framework.

---

# Open questions to settle before implementation

1. Should generic Responses providers send `max_output_tokens` in PR 1? Plan
   says yes; ChatGPT omits it in PR 2.
2. Should `cache_control=true` enable `prompt_cache_key` for Responses? Plan
   says yes, using the session ID. This keeps cache behavior meaningful across
   turns without adding a new config key.
3. Should the Responses adapter send `reasoning` when the model is absent from
   the models.dev catalog? Plan says omit (safe default). Add a provider override
   only if real usage requires it.
4. Should `/login` automatically open the model picker after selecting ChatGPT?
   Plan says yes when the current model is not in the catalog.
5. Should PR 2 be a stacked PR on PR 1 or wait for PR 1 to merge? Plan
   recommends waiting and rebasing, to keep review scope fixed.

---

# Acceptance criteria

PR 1:

- A provider with `api_type = "response"` completes a streaming text turn and a
  tool-call turn using an API key.
- A provider with `api_type = "message"` behaves as before.
- Switching provider mid-session preserves text, images, tool calls, and tool
  results; foreign thinking is dropped from the request but retained on disk.
- A session saved with one provider resumes under another provider.
- `cache_control` never appears in session JSON.
- `make check` passes.

PR 2:

- `/login` completes the browser flow, saves credentials, and selects ChatGPT.
- `/model` lists the ChatGPT account's models.
- A text turn and a tool-call turn complete through
  `https://api.openai.com/v1/responses`.
- `/logout` revokes and clears local credentials.
- Refresh failure produces a clear "run /login" message, not a crash.
- `make check` passes.

---

# Risks

- The neutral-transcript refactor touches display, tools, MCP, clipboard, and
  session code. Keep the adapter seam fixed and migrate call sites in small
  commits.
- Responses reasoning items with `encrypted_content` can be large; session files
  grow. This is the price of replaying reasoning across turns.
- Generic Responses providers may not implement the standard model catalog.
  Keep the manual `/models` fallback and let the user enter a model ID.
- Tool-call IDs from different providers are not compatible. Normalize per
  request and never mutate stored history.
- PR 2's refresh-token failure is an open OpenAI issue. Treat it as a product
  risk during the live spike, not as something the client can fix.

---

# Worktrees and sequencing

- PR 1 worktree: `<parent>/mini-agent-worktrees/response-api`.
  Branch: `feat/response-api-provider`.
- PR 2 worktree: `<parent>/mini-agent-worktrees/chatgpt-oauth`.
  Branch: `feat/chatgpt-oauth`, created after PR 1 merges.
- Copy `.env` into each worktree if it exists (this checkout has none;
  `ant.env`/`oai.env` are untracked and must not be committed).
- Run `make check` in each worktree before opening the PR.
- Keep user docs unchanged. The plan and research files are the only docs.
