# Research: Sign in with ChatGPT for mini-agent

Research notes on integrating **Sign in with ChatGPT (SIWC)** into mini-agent.
Written 2026-10-18 against OpenAI's published SIWC documentation (the flow was
opened to open-source apps around 2026-09-29), the official
[`openai/sign-in-with-chatgpt-devkit`](https://github.com/openai/sign-in-with-chatgpt-devkit)
reference implementation, and OpenAI Python SDK `3.35.1`. This document presents
options and tradeoffs; it does not make the final call.

---

## 0. Bottom line

- **The useful capability for mini-agent is ChatGPT plan usage**, not identity
  sign-in. It lets an eligible Plus/Pro user spend their ChatGPT plan on
  mini-agent's AI requests without creating an OpenAI API key.
- **mini-agent qualifies for the open-source route.** It is an Apache-2.0,
  locally-run CLI, which is exactly the target of the OSS flow. The flow needs
  no pre-issued client ID, no client secret, and no partner API key.
- **This is not a config change.** mini-agent speaks the Anthropic Messages API
  today. SIWC plan usage speaks the OpenAI Responses API. A second backend plus
  OAuth/token management is required.
- **Use the official flow only.** The unofficial Codex OAuth client
  (`app_EMoamEEZ73f0CkXaXp7hrann` / `chatgpt.com/backend-api/codex`) is
  unsupported and should not be implemented.
- **Do a live spike before committing to the full implementation.** Two facts
  cannot be settled from the docs alone: the exact tool declaration shape
  accepted by the plan-usage route, and a currently open refresh-token failure
  in the official DevKit (§3.5).

---

## 1. What "Sign in with ChatGPT" is

SIWC has two independent capabilities:

1. **Identity** — OIDC sign-in with a ChatGPT account. Returns a verified `sub`,
   name, email, and profile picture. It does **not** grant access to ChatGPT
   conversations or API resources.
2. **ChatGPT plan usage** — a separately consented permission that lets an
   eligible Plus/Pro user spend their plan or credits on the app's AI requests.
   Requests go to the public Responses API at `https://api.openai.com/v1` with
   the user's OAuth access token as the bearer credential.

mini-agent has no server, accounts, or login system, so identity-only sign-in
adds nothing. Plan usage is the capability that replaces an API key.

Availability as of 2026-10-18:

| Capability | Who can use it |
|---|---|
| ChatGPT plan usage, OSS flow | Open-source and locally hosted apps. Dynamic registration; no pre-issued client ID. |
| ChatGPT plan usage, commercial | Selected private clients / interest form. |
| Identity only | Selected commercial partners (waitlist). |

OpenAI's consumer help article says the launch is a "limited set of partners"
but explicitly points open-source developers at the self-serve developer flow:
"Supported open-source tools remain available to all ChatGPT users." The
developer quickstart says plan usage is "available to all open-source partners
and selected private clients." The practical reading is: mini-agent's
open-source, local-first use fits the documented OSS route, but **confirm with a
real Plus or Pro account in the spike** before building the full feature.

Sources: [overview](https://developers.openai.com/siwc/token-sharing-open-source),
[quickstart](https://developers.openai.com/siwc/quickstart),
[consumer help](https://help.openai.com/en/articles/20001542),
[DevDay recap](https://openai.com/index/devday-2026-recap/).

---

## 2. Why SIWC is a second provider, not a configuration change

mini-agent today is Anthropic-only and synchronous:

| Point | Location | Current |
|---|---|---|
| Client | `src/mini_agent/config.py:164-173` | `Anthropic(base_url=…)`; auth from `API_KEY_ENV` as a bearer token |
| Agent loop | `src/mini_agent/agent/agent.py:23-161` | `client.messages.stream(...)`, `stop_reason == "tool_use"` |
| Tools | `src/mini_agent/agent/tools/schemas.py` | Anthropic `name` / `description` / `input_schema` dicts |
| Tool dispatch | `src/mini_agent/agent/tools/handlers.py` | name → synchronous callable |
| History | `list[MessageParam]` | Anthropic content blocks: `text`, `image`, `tool_use`, `tool_result`, `thinking` |
| Display | `src/mini_agent/cli/display/stream.py` | Anthropic `content_block_delta` events |
| Model list | `src/mini_agent/cli/models.py:100-148` | Anthropic SDK `models.list()` or `/v1/models` with `data[]` |
| Usage | `src/mini_agent/cli/token.py` | Anthropic input / cache-creation / cache-read / output |

The Responses API has a different request and response shape:

| Concept | Anthropic Messages (now) | OpenAI Responses (SIWC) |
|---|---|---|
| Auth | `Authorization: Bearer <API key>` | `Authorization: Bearer <OAuth access token>` |
| System prompt | `system=` | top-level `instructions` (or `developer` input items) |
| Conversation | `messages` with content blocks | `input` array of message / function-call / function-output items |
| Tools | `tools=[{name, description, input_schema}]` | `additional_tools` input item containing `function` tools (or a `namespace` in top-level `tools`) |
| Tool call | `tool_use` block, `stop_reason=="tool_use"` | `function_call` output item |
| Tool result | `tool_result` block in the next user message | `function_call_output` item in the next `input` |
| Streaming | `content_block_delta` events | SSE `response.output_text.delta`, `response.completed`, `response.failed`, … |
| Max output | `max_tokens` | **unsupported on this route** — omit |
| Reasoning | `thinking` / `output_config.effort` | `reasoning.effort` (different vocabulary) |
| Prompt caching | `cache_control` | not exposed on this route |
| Success signal | final `Message` | `response.completed` |

So the integration needs OAuth, credential refresh, a Responses backend, and
message/tool translation. Keeping the Anthropic path untouched is both feasible
and desirable.

---

## 3. The official OSS protocol

Sources: [registration and sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in),
[accounts and sessions](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions),
[token reference](https://developers.openai.com/siwc/token-sharing-open-source/token-reference).

### 3.1 Host ID

Each installation (not each sign-in) gets a stable, opaque
`ext_agent_host_id`, persisted before the first sign-in. Accepted formats:

- `urn:ietf:params:oauth:jwk-thumbprint:…` — recommended, but optional.
- `urn:uuid:<uuid4>` — supported and simplest.
- `did:key:<key>`.

It is an identifier, not a credential; OpenAI does not verify possession of a
private key. Use one UUIDv4 per mini-agent installation (for example in
`~/.mini-agent/chatgpt-host.json`). Restarting the tool or signing in again must
not create a new host ID.

### 3.2 Dynamic client registration + authorization

Generate fresh `state`, OIDC `nonce`, and PKCE verifier per attempt. Start a
loopback listener on `127.0.0.1` **before** opening the browser. The callback
path is fixed to `/auth/callback`; only the port may vary, and it may vary
between sign-ins. Do not use `localhost`.

First sign-in:

```
https://auth.openai.com/api/accounts/authorize
  ?client_id=dynamic_agent_client
  &agent_name_hint=mini-agent
  &ext_agent_host_id=urn:uuid:...
  &response_type=code
  &redirect_uri=http://127.0.0.1:<port>/auth/callback
  &scope=openid profile email offline_access resource.invoke chatgpt.tokens.use.direct
  &resource=https://api.openai.com/v1
  &state=...
  &nonce=...
  &code_challenge_method=S256
  &code_challenge=<base64url(sha256(verifier))>
```

Later sign-ins reuse the saved issued `client_id` (for example `oaiapp_…`) and
omit `agent_name_hint`. The docs allow `id_token_hint` and `login_hint` as
optional account hints. The official DevKit deliberately sends only
`login_hint` and omits `id_token_hint`, because a token in a browser URL can leak
through browser history, referrers, or process arguments. That tradeoff is
reasonable for a CLI: omit `id_token_hint` by default; the user may see the
account picker.

`prompt=consent` should be sent only when the user explicitly re-enables plan
usage after declining. Do not force consent on routine sign-ins.

### 3.3 Callback and code exchange

The new-registration callback returns `code`, `state`, and the issued
`client_id`. Validate `state` with a constant-time comparison before using
anything. On `error=access_denied`, stop without exchanging a code.

Persist the issued `client_id` immediately after the callback, before the token
exchange. A one-time code can expire or fail after registration succeeds; without
this, a failed exchange would force another dynamic registration.

POST form-encoded to `https://auth.openai.com/api/accounts/oauth/token`:

```
grant_type=authorization_code
client_id=<ISSUED_CLIENT_ID>          # not dynamic_agent_client
code=<CODE>
code_verifier=<PKCE_VERIFIER>
redirect_uri=<EXACT_SAME_URI>
resource=https://api.openai.com/v1
```

No client secret. The token response contains `access_token`, `refresh_token`,
`id_token`, `token_type`, `expires_in`, `scope`, and `earliest_refresh_at`.

### 3.4 Validate the ID token, then store

Verify the `id_token` against OpenAI's JWKS:

- signature (`RS256`),
- `iss == https://auth.openai.com`,
- `aud == issued client_id`,
- `exp` / `iat`,
- `nonce` from this attempt,
- `azp == client_id` when present.

Use the verified `sub` as the account identity. Check the token response's
granted scopes for `chatgpt.tokens.use.direct`; a valid ID token alone does not
authorize plan usage. If that scope is missing, retain the sign-in but mark plan
usage as disabled and tell the user how to enable it.

Credential record (one per issued client ID):

```json
{
  "email": "user@example.com",
  "issuer": "https://auth.openai.com",
  "subject": "<id_token sub>",
  "client_id": "oaiapp_...",
  "ext_agent_host_id": "urn:uuid:...",
  "id_token": "...",
  "access_token": "...",
  "refresh_token": "...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "scopes": ["chatgpt.tokens.use.direct", "email", "offline_access", "openid", "profile", "resource.invoke"],
  "saved_at": "2026-10-18T00:00:00Z"
}
```

Write atomically with owner-only permissions (`0600` on Unix), never log tokens,
and keep credentials out of session files.

### 3.5 Refresh, revocation, and a current reliability issue

- Access token: 1 hour. Refresh token: 30 days, **rotating**; each refresh
  returns a replacement. Refresh with `grant_type=refresh_token`, the issued
  `client_id`, the saved `refresh_token`, and `resource=https://api.openai.com/v1`
  (omit `scope`).
- Store the replacement access/refresh token and expiry together. Serialize
  refreshes for the same credential record so two mini-agent processes do not
  race a rotating token.
- On sign-out, revoke the renewable session using the `revocation_endpoint`
  from `https://auth.openai.com/.well-known/openid-configuration`:
  form-encoded `token=<REFRESH_TOKEN>`, `token_type_hint=refresh_token`,
  `client_id=<issued id>`. Then clear local tokens but retain the registration
  and host ID for future sign-ins.
- On refresh errors (`invalid_grant`, `invalid_refresh_token`,
  `refresh_token_expired`, `refresh_token_invalidated`, `refresh_token_reused`),
  clear the unusable tokens and ask the user to sign in again. Do not erase
  credentials on a transient network or 5xx error.

**Open issue (2026-10-18):** live refreshes through the official OSS
registrations are failing in several clients, including OpenAI's own DevKit,
after the refresh token has been idle for a while. The DevKit issue reports
`400 invalid_grant` / `refresh_token_invalidated`; one later report observed
successful renewals during continuous use but failures after gaps longer than
about two hours. This may be an intentional preview limitation or a backend
bug, but it means a mini-agent session can die after one hour and require a
browser sign-in. This is the single biggest product risk in the feature today.
See [openai/sign-in-with-chatgpt-devkit#5](https://github.com/openai/sign-in-with-chatgpt-devkit/issues/5).

### 3.6 Models and inference

Model catalog: `GET https://api.openai.com/v1/models` with the OAuth bearer
token. This route's response is **not** the standard OpenAI `data[]` shape. The
docs use:

```bash
curl --fail-with-body --silent --show-error \
  https://api.openai.com/v1/models \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  | jq '[.models[] | select(.visibility == "list") | {slug, display_name}]'
```

Keep entries with `visibility == "list"`, show `display_name`, and pass `slug`
as `model`. Do not use the OpenAI SDK's `client.models.list()`, which expects a
standard `data[]` catalog.

Inference: `POST https://api.openai.com/v1/responses` with
`Authorization: Bearer <ACCESS_TOKEN>`.

Required on every request:

- `store: false`
- `stream: true`
- full history in `input`; no `previous_response_id` over HTTP
- system guidance in `instructions` or developer messages; explicit
  `{type:"message", role:"system"}` items are rejected

Unsupported request fields (omit them): `background`, `conversation`,
`max_output_tokens`, `max_tool_calls`, `metadata`, `moderation`, `multi_agent`,
`prompt`, `prompt_cache_retention`, `safety_identifier`, `temperature`,
`top_logprobs`, `top_p`, `truncation`, `user`.

Supported: text, images, and files when the selected model accepts them.
Unsupported: image generation, file search, Code Interpreter, native computer
use, hosted MCP/connectors, and `tool_search`.

Success is `response.completed`. `response.failed` can arrive after streaming
begins. Errors carry codes such as
`subscription_sharing_usage_limit_exceeded` (429),
`subscription_sharing_user_not_eligible` (403), and
`subscription_sharing_unsupported_capability` (400).

### 3.7 Tool declarations on the plan-usage route

The preview limitations say: "Group function/custom tools in namespaces or
supply them through `additional_tools` input items." Top-level `tools` with
plain function declarations also appear to work in live checks reported by other
clients, but that shape is not the documented contract. For a supported
implementation, use `additional_tools`:

```json
{
  "type": "additional_tools",
  "role": "developer",
  "tools": [
    {
      "type": "function",
      "name": "bash",
      "description": "Execute bash commands.",
      "strict": false,
      "parameters": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"]
      }
    }
  ]
}
```

The alternative is a namespace in top-level `tools`:

```json
{
  "type": "namespace",
  "name": "functions",
  "description": "mini-agent tools",
  "tools": [{"type": "function", "name": "bash", ...}]
}
```

A namespace route can return `function_call` items with a `namespace` field, so
the handler must read both `name` and (if present) `namespace`. The
`additional_tools` route avoids that ambiguity. **Verify both shapes in the
spike**, then keep the one that works.

We verified with OpenAI Python SDK `3.35.1` against a local capture server that:

- an `additional_tools` input item is serialized as shown above;
- `client.responses.stream(..., store=False)` sets `stream: true`;
- assistant text, `function_call`, and `function_call_output` input items are
  accepted in the same `input` array;
- a `function_call` output item parses as `ResponseFunctionToolCall` with
  `call_id`, `name`, and `arguments`.

### 3.8 Errors and recovery

Before a stream opens, the route may return a plain `{"detail":"…"}` body
instead of a structured error. Preserve status, body shape, error code, and
request ID. Do not assume every failure has `error.code`.

| Code | HTTP | Action |
|---|---|---|
| `subscription_sharing_user_not_eligible` | 403 | Explain; do not retry or loop OAuth |
| `subscription_sharing_usage_limit_exceeded` | 429 | Stop plan-backed requests; link to ChatGPT Settings → Usage |
| `subscription_sharing_usage_unavailable` | 503 | Retry later with bounded backoff |
| `subscription_sharing_unsupported_capability` | 400 | Inspect `error.param`; do not retry the same body |
| `subscription_sharing_route_not_supported` | 403 | Check method/endpoint |
| `subscription_sharing_invalid_user` | 401 | Preserve request ID; likely re-auth |
| `chatpass_v2_scope_not_authorized` | 403 | Check client/grant configuration |
| `subscription_sharing_user_unavailable` | 503 | Retry with bounded backoff |

OpenAI does not notify apps when a user disconnects the app in ChatGPT settings.
When a request or refresh proves the token is invalid, stop and ask the user to
sign in again.

Note from the SDK experiment: on `response.failed`, the Python SDK yields the
event but `stream.get_final_response()` raises a generic
`RuntimeError("Didn't receive a response.completed event.")`. Inspect
`response.failed` / `response.incomplete` / `error` events yourself and surface
the real code before calling `get_final_response()`. Also treat a stream that
ends without `response.completed` as a failure even if the SDK does not raise.

---

## 4. Proposed integration for mini-agent

### 4.1 UX and command surface

Follow OpenAI's UI/UX guidance: label the action **Continue with ChatGPT** and
keep it recognizably the same on later runs.

Minimal CLI surface:

```text
mini login          # sign in / reauthorize ChatGPT
mini logout         # revoke and clear local tokens
/provider           # includes the built-in "ChatGPT" provider
/model              # fetches the account's SIWC model catalog
/status             # shows provider and (optionally) the ChatGPT account
```

Existing CLI parsing uses `if args.prompt == "update"` for the only subcommand
(`src/mini_agent/cli/main.py:186-201`). Add `login` and `logout` the same way
rather than refactoring to argparse subparsers.

ChatGPT should be a built-in provider so `mini` works with no `config.toml`:

```python
Provider(
    id="chatgpt",
    name="ChatGPT",
    base_url="https://api.openai.com/v1",
    api_key_env=None,   # no API key
    kind="chatgpt",
)
```

`/provider` or `--provider chatgpt` selects it. If no credentials are present,
selecting it should run the login flow; if the user cancels, keep the previous
provider.

### 4.2 Config model

Add two fields to `Provider` (`src/mini_agent/config.py:47-52`):

```python
kind: str = "anthropic"          # "anthropic" | "chatgpt"
api_key_env: str | None = None
```

Keep `get_providers()` reading user tables exactly as today, then append the
built-in ChatGPT provider. `get_provider()` no longer has to fail when no
`[providers]` table exists. `_build_client()` remains Anthropic-only; add a
separate `get_chatgpt_client()` or, better, a `run_turn()` selector (§4.3).

Do not expose a user-facing `kind = "openai-responses"` yet. That is a second
provider abstraction for a protocol mini-agent does not otherwise support.

### 4.3 Agent backend seam

Keep the existing Anthropic-shaped `list[MessageParam]` as mini-agent's canonical
history. Add one small seam in `agent/`:

```python
@dataclass
class Turn:
    content: list[ContentBlock]
    stop_reason: str          # "tool_use" | "end_turn"
    usage: Usage

def run_turn(messages: list[MessageParam]) -> Turn: ...
```

- `AnthropicTurn` wraps the current `messages.stream(...)`, calls
  `display_stream_events`, and returns `response.content`,
  `response.stop_reason`, and mapped usage.
- `ChatGPTTurn` builds the Responses `input`, calls
  `client.responses.stream(...)`, drives a Responses equivalent of
  `display_stream_events`, and converts the final output into Anthropic-style
  content blocks and a `Turn`.

`agent_loop` then keeps its shared tool execution, interrupt, back-fill, and
session behavior (`src/mini_agent/agent/agent.py:88-151`). This is the smallest
change that avoids duplicating the loop and leaves the Anthropic path intact.

### 4.4 Message translation (Responses input)

Canonical history → `input` on every request:

- Prepend one `additional_tools` item built from `TOOLS`
  (`src/mini_agent/agent/tools/schemas.py`), mapping `input_schema` →
  `parameters`, with `strict: false`.
- User string → `{"role":"user","content":"…"}`.
- User content list:
  - `text` → `{"type":"input_text","text":…}`
  - `image` → `{"type":"input_image","image_url":"data:<media_type>;base64,<data>"}`
  - `tool_result` → a top-level
    `{"type":"function_call_output","call_id":tool_use_id,"output":…}` item;
    multiple results become multiple items.
- Assistant content:
  - `text` → `{"role":"assistant","content":…}`
  - `tool_use` → `{"type":"function_call","call_id":id,"name":name,"arguments":json.dumps(input)}`
  - `thinking` → omit (see open question in §8).
- Tool output can be a string or a list of content blocks. For list outputs,
  emit `input_text` / `input_image` items; map `is_error` to a leading
  `"Error: "` because `function_call_output` has no `is_error` field.

Responses output → canonical assistant message:

- `message` output items → `text` blocks.
- `function_call` output items → `tool_use` blocks with
  `id=call_id`, `name=name`, `input=json.loads(arguments)`.
- Set `stop_reason="tool_use"` if any function call was returned; otherwise
  `"end_turn"`.
- Ignore reasoning items for now (see §8).

This keeps session files unchanged and makes provider switching mid-session
possible.

### 4.5 System prompt, reasoning, and usage

- Send `SYSTEM` as `instructions`. Do not add a `system` role input item.
- Map reasoning effort:
  - `disabled` → `reasoning.effort = "none"`
  - `adaptive` → omit `reasoning`
  - `low` / `medium` / `high` / `xhigh` / `max` → pass through
  - If the selected model rejects reasoning, surface
    `subscription_sharing_unsupported_capability` with `error.param`; do not
    silently retry a different body.
- Do not send `max_output_tokens`; the existing `get_max_output_tokens()` value
  is Anthropic-only.
- Ignore `cache_control`, `thinking`, and `output_config` on this path.
- Map usage:
  - `output_tokens` → `Usage.output_tokens`
  - `input_tokens - input_tokens_details.cached_tokens` → `Usage.input_tokens`
  - `input_tokens_details.cached_tokens` → `Usage.cache_read_input_tokens`
  - `cache_creation_input_tokens = 0`

### 4.6 Streaming display

`src/mini_agent/cli/display/stream.py` is Anthropic-specific. Add a sibling
function for Responses events, reusing the same Rich `Live` + `Markdown`
rendering:

- `response.output_text.delta` → append text.
- `response.reasoning_summary_text.delta` → optional thinking display.
- `response.failed` / `response.incomplete` / `error` → stop and surface the
  code.
- `response.completed` → success.

The OpenAI SDK's `client.responses.stream(...)` returns a context manager with
`get_final_response()`, mirroring `messages.stream(...)`.

### 4.7 Model picker and status

- Branch `fetch_models()` on provider kind. For ChatGPT, call
  `GET /v1/models` with the OAuth bearer token, parse `.models[]`, filter
  `visibility == "list"`, and return `slug`s. Keep `display_name` only if the
  picker can show it without widening the existing `select_model` API.
- `models.dev` limits may not know ChatGPT slugs; `format_model` will show the
  bare ID and `/status` will hide the context window. That is acceptable.
- Optionally show the account email and plan-usage status in `/status` by
  reading the credential record. Do not show tokens.

### 4.8 Auth module and storage

Suggested files:

```text
src/mini_agent/chatgpt/auth.py       # discovery, login, callback, exchange, refresh, revoke
src/mini_agent/chatgpt/credentials.py# load/save/validate, 0600, atomic write, lock
src/mini_agent/chatgpt/client.py     # Responses client + translation (or agent/backends)
```

Storage:

- `~/.mini-agent/chatgpt-host.json` — `{"version":1,"id":"urn:uuid:…"}`
- `~/.mini-agent/chatgpt.json` — the credential record from §3.4

Use a temp file + `os.replace` for atomic writes, `os.chmod(0o600)` on Unix, and
a lock (for example `fcntl.flock` / `msvcrt.locking`, or a small `filelock`
dependency) around refresh. Validate the file shape on read; on corrupt or
unreadable credentials, preserve the file and report an error rather than
silently overwriting it.

The published docs' own example is a `0600` JSON file, which matches
mini-agent's existing `~/.mini-agent/.env` practice. The DevKit goes further and
requires OS-backed encryption (Keychain / DPAPI / Secret Service) with no
plaintext fallback, because it targets desktop apps with a renderer boundary.
For a local CLI, `0600` is a defensible baseline; if the security bar is higher,
use the OS keychain via `keyring` and keep only the non-secret host ID on disk.
Decide this explicitly in the implementation plan.

### 4.9 Dependencies

- `openai` — recommended. It handles SSE framing, function-call parsing, and
  response models. Hand-rolling SSE is possible but adds fragile parsing for
  little benefit.
- `PyJWT[crypto]` — ID-token signature verification against JWKS. This pulls in
  `cryptography`, which is a compiled dependency. The alternative is to skip
  signature verification (not acceptable) or use another JOSE library (same
  `cryptography` cost).
- Optional: `filelock` for cross-platform refresh locking.

Use stdlib `urllib.request` for discovery/token/revocation HTTP, or declare
`httpx` explicitly if you prefer it.

### 4.10 File-level change list

| File | Change |
|---|---|
| `pyproject.toml` | Add `openai`, `PyJWT[crypto]` (and `filelock` if used) |
| `src/mini_agent/config.py` | `Provider.kind`, optional `api_key_env`, built-in ChatGPT provider, backend selector |
| `src/mini_agent/chatgpt/…` | OAuth, credential store, discovery, refresh, revoke, Responses client |
| `src/mini_agent/agent/agent.py` | Extract `run_turn`; shared tool loop; ChatGPT branch |
| `src/mini_agent/agent/tools/schemas.py` | Reuse as-is; convert `input_schema` at the boundary |
| `src/mini_agent/cli/display/stream.py` | Add Responses event rendering |
| `src/mini_agent/cli/main.py` | `login` / `logout` commands; `/login` if desired |
| `src/mini_agent/cli/providers.py` | Built-in ChatGPT entry; trigger login when unauthenticated |
| `src/mini_agent/cli/models.py` | ChatGPT model catalog branch |
| `src/mini_agent/cli/status.py` | Optional account/plan display |
| `docs/providers.md`, `docs/quickstart.md`, `docs/config.md`, `docs/usage.md` | Document the new provider and commands |
| `tests/…` | See §5.2 |

---

## 5. Testing plan

### 5.1 Live spike (do first)

With a real Plus or Pro account, verify:

1. Dynamic registration, callback state validation, code exchange, and
   `chatgpt.tokens.use.direct` in the granted scopes.
2. `GET /v1/models` shape and a model slug.
3. A streaming text response with `store:false`, `stream:true`, `instructions`.
4. `additional_tools` with one `bash` function → `function_call` →
   `function_call_output` → `response.completed`.
5. A second tool round in the same conversation; then a third turn after a
   restart.
6. Whether reasoning items must be echoed back for multi-turn tool use.
7. `max_output_tokens` is rejected (confirm omit).
8. Refresh after one hour; refresh after a long idle period (the known issue).
9. At least one Plus and one Pro account if available.

If step 4 fails with the `additional_tools` shape, try the namespace shape from
§3.7. If both fail, the feature is blocked on the API contract.

### 5.2 Unit tests

- OAuth URL construction: PKCE S256, state/nonce, scope, resource, host ID,
  `agent_name_hint` only on first registration.
- Callback validation: state mismatch, duplicate parameters, wrong host/path,
  `error=access_denied`, missing issued client ID, reauth without callback
  `client_id`.
- Token exchange and refresh request bodies; rotated refresh token persisted
  before use.
- ID-token validation with a generated RSA key and a local JWKS: signature,
  issuer, audience, expiry, nonce, `azp`.
- Credential store: atomic write, `0600`, corrupt-file handling, refresh lock.
- Translation both ways: text, images, multiple tool calls, multiple tool
  results, `is_error`, thinking blocks dropped, assistant text + tool calls.
- Reasoning effort mapping.
- Model catalog parsing (`.models[]`, `visibility`, `slug`) and rejection of the
  standard `data[]` shape.
- Usage mapping, including cached tokens.
- Error mapping: 401/403/429/503, `response.failed` mid-stream,
  `response.incomplete`, stream ending without `response.completed`.

Use a local HTTP stub for OAuth and a synthetic SSE stream for inference;
do not require network access or live credentials in tests.

---

## 6. Alternatives considered

- **Codex app-server as a subprocess.** Supported by OpenAI and works with an
  OAuth access token (`ACCESS_TOKEN`, `wire_api="responses"`,
  `base_url="https://api.openai.com/v1"`). It offloads the entire agent loop to
  Codex, adds a large external dependency, and contradicts mini-agent's
  "minimal, own loop" design. Rejected.
- **Unofficial Codex OAuth client + `chatgpt.com/backend-api/codex`.** Works
  today, but is unsupported, couples mini-agent to Codex's private client ID,
  and risks account/ToS issues. Rejected.
- **Identity-only sign-in.** Adds accounts and a login system to a local CLI
  with no server. Rejected.
- **Local OpenAI-compatible proxy (`openai-oauth`, LiteLLM, etc.).** Adds a
  second process and a translation layer outside mini-agent. Rejected.
- **Hand-rolled HTTP/SSE instead of the OpenAI SDK.** Smaller dependency
  surface, but more code and more failure modes in event parsing. Not
  recommended unless dependency size is a hard constraint.

---

## 7. Risks

- **Refresh reliability.** The open refresh failure (§3.5) can force hourly or
  daily browser sign-ins. This is the top risk; validate before building.
- **Preview API.** The request contract, model catalog, or error codes can
  change. Pin behavior behind tests and keep the Anthropic path independent.
- **Tool contract ambiguity.** `additional_tools` is documented but the exact
  live behavior (plain functions vs namespace, `namespace` on calls) should be
  verified.
- **Reasoning continuity.** Dropping reasoning items from history may reduce
  quality for reasoning models, and in the worst case break multi-turn tool use.
  Test; if needed, retain raw Responses reasoning items in a provider-specific
  session sidecar.
- **Eligibility.** The launch partner list is limited. The OSS flow is
  self-serve, but confirm a real account can use plan inference.
- **Usage limits.** Plus users share a 5-hour window across all apps; Pro users
  do not. An app-level weekly limit can also stop requests. Never auto-retry a
  429 usage-limit error.
- **Security.** Refresh tokens are long-lived credentials. Keep them out of
  logs, URLs, session files, and analytics. Use `0600` + atomic writes, or an OS
  keychain.
- **Dependency/license.** The DevKit is under the **Sign-in with ChatGPT DevKit
  Noncommercial License v1.0**, which is not compatible with mini-agent's
  Apache-2.0 distribution. Use it as a reference, not as copied code. The
  OpenAI Python SDK and PyJWT are separately licensed.
- **Windows.** `0600`, atomic replace, and file locking need platform-specific
  handling. Test on Windows if it is a supported target.

---

## 8. Open questions

1. Does a real Plus/Pro account accept mini-agent's `additional_tools` tool
   declarations on the public Responses route today?
2. Are reasoning items required in subsequent `input` arrays for multi-turn
   tool use, or can they be dropped?
3. Is the refresh failure an intentional preview limit or a bug that will be
   fixed soon? If it persists, is the acceptable UX "re-login after idle" or
   should the feature wait?
4. Is a `0600` credential file acceptable, or should mini-agent adopt an
   OS-keychain dependency?
5. Should `mini login` support multiple ChatGPT accounts, or is one active
   account (logout + login to switch) sufficient for the first version?
6. Should `/provider` auto-run login when ChatGPT is selected without
   credentials, or require `mini login` first?

---

## 9. Effort estimate

| Work | Estimate |
|---|---|
| Live spike + contract confirmation | 0.5–1 day |
| OAuth, discovery, PKCE, callback, JWKS validation | 1–1.5 days |
| Credential store, refresh, revoke, locking | 1 day |
| Responses backend + message/tool translation + streaming | 2–3 days |
| CLI/model/status integration + docs | 1 day |
| Tests (unit + stub integration) | 1–2 days |
| **Total** | **~5–8 days** |

The estimate assumes the spike confirms the tool shape and a workable refresh
path. If refresh remains broken, add a re-login fallback or defer the feature.

---

## Sources

- SIWC overview — <https://developers.openai.com/siwc/token-sharing-open-source>
- Quickstart — <https://developers.openai.com/siwc/quickstart>
- Registration and sign-in — <https://developers.openai.com/siwc/token-sharing-open-source/sign-in>
- Accounts and sessions — <https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions>
- Token reference — <https://developers.openai.com/siwc/token-sharing-open-source/token-reference>
- Models and inference — <https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference>
- Preview limitations — <https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations>
- Errors and recovery — <https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery>
- Codex app-server — <https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server>
- UI/UX guidelines — <https://developers.openai.com/siwc/ui-ux-guidelines>
- Request a client ID (identity-only waitlist) — <https://developers.openai.com/siwc/request-client-id>
- Consumer help article — <https://help.openai.com/en/articles/20001542>
- DevDay 2026 recap — <https://openai.com/index/devday-2026-recap/>
- DevKit — <https://github.com/openai/sign-in-with-chatgpt-devkit>
- DevKit refresh failure — <https://github.com/openai/sign-in-with-chatgpt-devkit/issues/5>
- Codex source (tool serialization, Responses Lite) — <https://github.com/openai/codex>
- OpenAI Python SDK Responses streaming — installed `openai==3.35.1`, used for the offline request/SSE capture described in §3.7
