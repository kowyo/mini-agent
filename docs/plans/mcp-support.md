# Plan: MCP support for mini-agent

Implements [#83](https://github.com/kowyo/mini-agent/issues/83). Based on the research in
[`docs/research/mcp-support.md`](../research/mcp-support.md) and
[`docs/research/mcp-v2.md`](../research/mcp-v2.md).

## Decisions

| Decision | Choice | Rationale (research ref) |
|---|---|---|
| Approach | Native tools-only client via the official `mcp` SDK (Option A, then B) | Matches #83's scope; highest learning value; SDK handles era negotiation between 2026-07-28 and 2025 handshake servers (§3.1, §4) |
| Dependency | `mcp>=2` (`uv add mcp`) | v2 `Client` API; speaks all spec revisions; Python 3.10+ fits our 3.14 (§4) |
| Transports | stdio first (milestone 1), Streamable HTTP second (milestone 2) | stdio covers the motivating chrome-devtools-mcp use case; HTTP is a small increment (§8 A/B) |
| Config | Standard `mcpServers` JSON at `~/.mini-agent/mcp.json` and `<cwd>/.mini-agent/mcp.json` | The de-facto ecosystem format — users paste server READMEs unchanged (§5.1); paths per #83 |
| Config merge | Per-server-name override, project wins; no field merging | Ecosystem norm (§7.1) |
| Tool naming | `mcp__<server>__<tool>`, sanitize to `[A-Za-z0-9_-]` | Widely recognized convention; avoids cross-server collisions; satisfies the Anthropic tool-name pattern (§7.3) |
| Sync↔async bridge | One background event-loop thread owning all MCP I/O (`McpRuntime`) | mini-agent is fully synchronous; stdio sessions must outlive individual calls (§8 A) |
| Spawn timing | All configured servers connect at startup; a failed server is reported and skipped | Simplest correct v1; lazy connect is a later optimization (§8 C) |
| Protocol surface | `tools/list` (paginated) + `tools/call` only; ignore `list_changed`, resources, prompts, sampling, roots | Spec-blessed minimum; the rest is optional or deprecated (§3.6, mcp-v2 Q5) |
| Result mapping | text → string / text blocks; image → base64 image block (same shape as `run_read`); `is_error` → `is_error: true` on the tool_result | Fits existing content-block support (§7.6) |
| Output cap | 50,000 chars, reuse the `MAX_OUTPUT` idea from `base.py:10` | Existing precedent; matches ecosystem caps (§8 cross-cutting) |
| Timeouts | 10 s connect, 60 s per tool call, per-server `timeout` override in config | Ecosystem defaults (§8 cross-cutting) |
| Auth (HTTP) | Static `headers` from config with `${VAR}` env expansion; no OAuth | Bearer tokens cover most remote servers; OAuth is where client code balloons (§4, §5.3) |

Out of scope (v1): HTTP+SSE legacy transport, OAuth, resources/prompts, `list_changed`
re-listing, lazy/proxy tool representation (pi-style), code-mode execution.

## Config format

```json
{
  "mcpServers": {
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp"],
      "env": {},
      "timeout": 60
    },
    "github": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": {"Authorization": "Bearer ${GITHUB_PAT}"}
    }
  }
}
```

- Entry with `command` (no `type`) → stdio. `type: "http"` + `url` → Streamable HTTP. Any other
  `type` → error naming the server.
- `${VAR}` expansion in `env` values, `url`, and `headers` from the process environment
  (mini-agent already loads `~/.mini-agent/.env` in `config.py:41`).
- `env` is additive: the SDK merges it over its minimal default env allow-list.
- Both files optional; missing files mean no MCP servers.

## Milestone 1 — stdio (core)

New package `src/mini_agent/agent/mcp/`:

1. **`config.py`** — `load_mcp_servers() -> dict[str, ServerConfig]`
   - Read + JSON-parse both config paths, merge per-server-name (project wins).
   - Validate each entry into a small `ServerConfig` dataclass (stdio vs http variant);
     collect per-entry errors instead of failing the whole file.
   - `${VAR}` expansion helper.

2. **`runtime.py`** — `McpRuntime` (sketch in research §8 A)
   - Background daemon thread running an asyncio event loop; `AsyncExitStack` owns
     `Client(stdio_client(StdioServerParameters(...)))` contexts.
   - `connect(name, cfg)` with 10 s timeout; on failure record the error, mark server failed.
   - `call_tool(server, tool, args)` via `run_coroutine_threadsafe(...).result(timeout)`;
     `TimeoutError` and a dead subprocess become error strings, never exceptions that kill
     `agent_loop`.
   - `shutdown()` closes the stack (SDK reaps subprocesses: close stdin → wait → SIGTERM →
     SIGKILL); registered via `atexit` and called from the CLI exit path.

3. **`tools.py`** — registration and mapping
   - Per connected server: paginated `list_tools()`; for each tool build an Anthropic
     `ToolParam` `{name: mcp__<server>__<tool>, description, input_schema: <inputSchema
     pass-through>}` and a handler closure for `TOOL_HANDLERS`.
   - Result mapping: `TextContent` → text (joined string, or text blocks when mixed);
     `ImageContent` → `{"type": "image", "source": {"type": "base64", ...}}` (same shape
     `file.py`'s `run_read` returns); other block types → their JSON as text. Truncate past
     the output cap. `result.is_error` → tool_result `is_error: true`.

4. **Wiring**
   - `agent/tools/__init__.py` (or a startup hook in `cli/main.py`): after building the static
     `TOOLS`/`TOOL_HANDLERS`, extend both with the MCP entries. Print a one-line per-server
     status (`connected <name>: N tools` / `failed <name>: <reason>`) at startup.
   - `agent/agent.py:113-119`: allow handlers to signal errors so the tool_result can carry
     `"is_error": True` (small, additive change; existing tools unaffected).
   - `pyproject.toml`: add `mcp>=2`.

5. **Tests** (`tests/test_mcp_config.py`, `tests/test_mcp_tools.py`)
   - Config: parsing, merge precedence, `${VAR}` expansion, invalid entries.
   - Naming: sanitization, collision behavior.
   - Mapping: content-block conversion, truncation, `is_error` propagation — against a stub
     client, no real server needed.
   - One integration test against a trivial in-repo stdio server script (the `mcp` package can
     serve as well as connect), marked so it can be skipped where `npx`-style spawning is
     unavailable.

Manual acceptance: `mini` in a project whose `.mini-agent/mcp.json` configures
`chrome-devtools-mcp`; ask the model to take a screenshot; image lands in the conversation.

## Milestone 2 — Streamable HTTP

- `ServerConfig` http variant → `streamable_http_client(url, http_client=...)` with an
  `httpx` client built from config `headers` (+ `${VAR}` expansion) and timeouts.
- Same runtime, registration, and mapping code paths; only `connect()` branches on transport.
- Tests: config variant parsing; connect-failure reporting. (Wire-level behavior is the SDK's,
  already covered by its own tests.)

Manual acceptance: connect a public Streamable HTTP server (e.g. Context7) and call a tool.

## Milestone 3 — polish

- `docs/mcp.md` user guide: config format, both transports, `${VAR}` expansion, troubleshooting
  (server prints to stdout, startup timeout, name collisions).
- README + `docs/config.md` cross-links.
- Startup latency: connect servers in parallel on the runtime loop (`asyncio.gather`).
- Optional (defer freely): a `/mcp` CLI command listing servers, status, and tool counts.

## Failure modes handled (research §8 A)

| Failure | Behavior |
|---|---|
| Server fails to start / version mismatch at connect | Report once at startup, mark failed, continue without it |
| Server crashes mid-conversation | Next call returns a tool_result with `is_error: true`; server marked failed; loop continues |
| Hung tool call | 60 s (configurable) timeout → error tool_result |
| Server pollutes stdout | SDK surfaces parse errors; stderr shown when debugging |
| Tool name collision | Namespacing prevents cross-server; duplicate final names get a numeric suffix and a warning |
| Giant output | Truncated at the cap with a marker, like `MAX_OUTPUT` |

## Open questions (decide during implementation)

1. Where exactly startup connection happens: eager in `cli/main.py` before the first prompt, or
   on first `agent_loop` entry (keeps `mini --help` fast). Leaning: first prompt.
2. Whether server `instructions` (returned at connect) get appended to the system prompt in v1.
   Leaning: no — revisit after real usage.
3. Numeric-suffix vs error on (rare) post-sanitization name collisions.
