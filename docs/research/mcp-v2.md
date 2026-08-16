# Research: "MCP v2" — what it is and what it means for a small Python MCP client

Researched: 2026-08-16. Primary sources: the official MCP spec site/blog and GitHub
SEPs, with Cloudflare's posts used as the entry point. Every claim is cited inline.

## TL;DR

"MCP v2" is shorthand for the **official MCP spec revision `2026-07-28`**, released
2026-07-28 and **current** as of today. It turns MCP from a bidirectional, stateful,
handshake-based protocol into a **stateless request/response protocol**: no
`initialize` handshake, no `Mcp-Session-Id`, server-initiated requests replaced by a
retry pattern (MRTR), and Roots/Sampling/Logging deprecated. It shipped with updated
Tier 1 SDKs (TypeScript, Python `mcp` 2.0.0, Go, C#). Cloudflare's post
([blog.cloudflare.com/mcp-v2/](https://blog.cloudflare.com/mcp-v2/), 2026-08-06) is
accurate advocacy for that release, not a separate proposal.

---

## 1. What is "MCP v2"?

- **It is an official spec revision, already released.** The MCP versioning page
  states: "The **current** protocol version is **2026-07-28**"
  ([modelcontextprotocol.io/specification/versioning](https://modelcontextprotocol.io/specification/versioning),
  checked 2026-08-16). MCP revisions are named by date (`YYYY-MM-DD`), not "v2" —
  the previous revision was `2025-11-25`.
- **Where "v2" comes from:** the SDKs. The Python `mcp` package jumped to **2.0.0 on
  2026-07-28** ([pypi.org/project/mcp/](https://pypi.org/project/mcp/), checked
  2026-08-16), and Cloudflare's changelog calls the TypeScript release "MCP SDK v2"
  ([developers.cloudflare.com/changelog/post/2026-07-27-agents-sdk-v0.20.0-mcp-sdk-v2/](https://developers.cloudflare.com/changelog/post/2026-07-27-agents-sdk-v0.20.0-mcp-sdk-v2/)).
  Cloudflare's blog URL slug `mcp-v2` popularized the label.
- **Who's behind it:** the MCP project itself, governed since 2025-12-09 under the
  **Agentic AI Foundation** (a Linux Foundation directed fund co-founded by
  Anthropic, Block, and OpenAI;
  [blog.modelcontextprotocol.io/posts/2025-12-09-mcp-joins-agentic-ai-foundation/](https://blog.modelcontextprotocol.io/posts/2025-12-09-mcp-joins-agentic-ai-foundation/),
  2025-12-09). The release announcement is signed by lead maintainers **David Soria
  Parra and Den Delimarsky**
  ([blog.modelcontextprotocol.io/posts/2026-07-28](https://blog.modelcontextprotocol.io/posts/2026-07-28),
  2026-07-28). Changes go through the **SEP process** (Specification Enhancement
  Proposals, numbered after their GitHub PR; formalized by
  [SEP-1850](https://github.com/modelcontextprotocol/specification/pull/1850)), with
  working/interest groups established in 2025
  ([blog.modelcontextprotocol.io/posts/2025-11-25-first-mcp-anniversary/](https://blog.modelcontextprotocol.io/posts/2025-11-25-first-mcp-anniversary/),
  2025-11-25).
- **Cloudflare's role:** advocate and early implementer, not author. Cloudflare
  contributed the Web-Standards replatform of the TypeScript SDK and `createMcpHandler`,
  and ran the release candidate in production before finalization
  ([blog.cloudflare.com/mcp-v2/](https://blog.cloudflare.com/mcp-v2/), 2026-08-06).

## 2. Concrete changes vs. the previous spec (2025-11-25)

All from the official changelog
([modelcontextprotocol.io/specification/2026-07-28/changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)):

| Change | SEP | Detail |
|---|---|---|
| No handshake | [SEP-2575](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2575) | `initialize`/`initialized` removed. Every request carries `io.modelcontextprotocol/protocolVersion`, `clientCapabilities`, and (SHOULD) `clientInfo` in `_meta`. Mismatch → `UnsupportedProtocolVersionError` (-32022). |
| No protocol sessions | [SEP-2567](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2567) | `Mcp-Session-Id` header removed; list endpoints no longer vary per connection. Cross-call state = explicit server-minted handles passed as ordinary tool arguments. |
| `server/discover` | SEP-2575 | New mandatory-to-implement RPC returning supported versions, capabilities, identity. Optional for clients to call. |
| MRTR (Multi Round-Trip Requests) | [SEP-2322](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2322) | Replaces server-initiated `elicitation/create`, `sampling/createMessage`, `roots/list`. Server returns `resultType: "input_required"` with `inputRequests`; client retries the original request with `inputResponses`. All results now carry a required `resultType` (`"complete"` or `"input_required"`); results from older servers that omit it MUST be treated as `"complete"`. |
| Streamable HTTP simplified | SEP-2575 | GET endpoint and `resources/subscribe` removed → single opt-in `subscriptions/listen` POST stream for change notifications. SSE resumability (`Last-Event-ID`) removed — a broken stream means re-issue the request. Closing the response stream = cancellation ([transport spec](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)). |
| Routing headers | [SEP-2243](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243) | `Mcp-Method` and `Mcp-Name` headers REQUIRED on Streamable HTTP POSTs (plus existing `MCP-Protocol-Version`); servers MUST validate header↔body match (-32020 `HeaderMismatch`). Optional `x-mcp-header` schema annotation mirrors tool params into `Mcp-Param-*` headers — clients MUST support it. |
| Cacheable lists | [SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549) | `tools/list`, `prompts/list`, `resources/list`, `resources/read`, `resources/templates/list` results carry `ttlMs` + `cacheScope`; tool lists SHOULD be deterministically ordered for LLM prompt-cache hits. |
| Auth hardening | [SEP-2468](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2468), [SEP-837](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/837), [SEP-2352](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2352) | RFC 9207 `iss` validation MUST be done by clients before redeeming an auth code; `application_type` required in DCR; credentials keyed by issuer, never reused across authorization servers. |
| DCR deprecated | [PR #2858](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2858) | Dynamic Client Registration deprecated in favor of **Client ID Metadata Documents (CIMD)**; still works for backward compat. Cloudflare says removal is slated after summer 2027 ([mcp-v2 post](https://blog.cloudflare.com/mcp-v2/)). |
| Features deprecated | [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577), [SEP-2596](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2596) | **Roots, Sampling, Logging** deprecated (migrations: tool params/config instead of roots; direct LLM APIs instead of sampling; stderr/OpenTelemetry instead of logging). Legacy HTTP+SSE transport formally Deprecated. Also removed: `ping`, `logging/setLevel`. |
| Tasks → extension | [SEP-2663](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2663) | Experimental tasks moved out of core into the `io.modelcontextprotocol/tasks` extension; polling via `tasks/get`. Extensions framework formalized (`extensions` in capabilities); MCP Apps and Enterprise-Managed Authorization are also extensions. |
| Lifecycle policy | SEP-2596 | Features are Active/Deprecated/Removed; deprecated features stay ≥12 months (90 days in an expedited exception) ([feature lifecycle](https://modelcontextprotocol.io/community/feature-lifecycle)). |
| Misc | [SEP-2106](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2106), [SEP-414](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/414) | Full JSON Schema 2020-12 allowed in tool schemas; OpenTelemetry `traceparent`/`tracestate` conventions in `_meta`; error-code range -32020…-32099 reserved for the spec. |

Note on "code execution": **it is not part of the 2026-07-28 spec.** Code
Mode is a Cloudflare/Anthropic *pattern* (see §3), applied at the server or client
level on top of ordinary MCP tools.

## 3. What problems motivated each change (the v1 pain points)

- **Stateful sessions were a stdio legacy.** stdio pipes are inherently a session, so
  the protocol baked in a handshake and `Mcp-Session-Id`. Remote servers inherited
  sticky sessions: load balancers needed affinity, autoscalers had to preserve
  sessions, deployments had to drain them, and SSE message replay (`Last-Event-ID`)
  required server-side storage
  ([blog.cloudflare.com/mcp-v2/](https://blog.cloudflare.com/mcp-v2/), 2026-08-06;
  [changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)).
  Statelessness lets "requests hit any instance behind a round-robin load balancer
  without shared storage"
  ([release post](https://blog.modelcontextprotocol.io/posts/2026-07-28), 2026-07-28).
- **Server-initiated requests required a held-open stream.** Elicitation/sampling/roots
  meant the server sent JSON-RPC *requests* back over a long-lived SSE stream — the
  main thing forcing sessions. MRTR replaces this with plain retries
  ([MRTR pattern](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr)).
- **Opaque JSON bodies blocked HTTP infrastructure.** Gateways, WAFs, and rate
  limiters had to parse JSON-RPC to know a request was `tools/call search`. The
  `Mcp-Method`/`Mcp-Name` headers make MCP legible to ordinary HTTP tooling
  ([SEP-2243](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243)).
- **Token cost / prompt-cache misses.** Nondeterministic tool ordering broke LLM
  prompt caches across reconnects; clients re-fetched lists with no freshness signal.
  Hence deterministic ordering + `ttlMs`/`cacheScope`
  ([SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549)).
- **Context bloat from many tools (the Code Mode motivation).** Exposing the
  Cloudflare API's 2,500+ endpoints as individual tools would cost ~2M tokens; their
  two-tool code-execution server (`search` + `execute` over a sandboxed typed SDK)
  costs ~1,000 tokens — a claimed 99.9% input-token reduction
  ([blog.cloudflare.com/code-mode-mcp/](https://blog.cloudflare.com/code-mode-mcp/),
  2026-02-20; same idea as Anthropic's
  [Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp),
  2025-11). This N-tools×M-servers schema-injection problem is solved by *pattern*,
  not by the spec.
- **OAuth complexity and vulnerabilities.** DCR meant every client registered
  dynamically with every server (operational burden, weak identity) → CIMD. The
  RFC 9207 `iss` check closes an authorization-server mix-up attack; issuer-bound
  credentials stop cross-issuer token confusion
  ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)).
- **Rarely-implemented client features.** Roots/Sampling/Logging added client-side
  complexity that most clients never implemented well; each now has a simpler
  substitute ([SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)).

## 4. Timeline and adoption reality (as of 2026-08-16)

- **Shipped, not speculative.** `2026-07-28` is the *current* revision on the official
  site ([versioning page](https://modelcontextprotocol.io/specification/versioning)).
  Released 2026-07-28 with Tier 1 SDK support: TypeScript, **Python (`mcp` 2.0.0)**,
  Go, C#; Rust in beta
  ([release post](https://blog.modelcontextprotocol.io/posts/2026-07-28)).
- Revision history: `2024-11-05` (HTTP+SSE) → `2025-03-26` (Streamable HTTP,
  sessions) → `2025-06-18` → `2025-11-25` (CIMD, extensions, experimental tasks) →
  `2026-07-28` (stateless).
- **Production use predates finalization:** Sentry and others ran the release
  candidate in prod; Cloudflare's stateless Code Mode server has served "billions of
  tool calls" ([blog.cloudflare.com/mcp-v2/](https://blog.cloudflare.com/mcp-v2/),
  2026-08-06 — vendor claim).
- **The old world still dominates deployed servers.** 2025-era servers (handshake +
  `Mcp-Session-Id`) remain everywhere; the spec defines explicit backward-compat
  probing between "eras," and deprecated features (legacy SSE transport, DCR, Roots/
  Sampling/Logging) must keep working ≥12 months, i.e. into ~mid-2027
  ([transport backward compat](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http#backward-compatibility);
  [feature lifecycle](https://modelcontextprotocol.io/community/feature-lifecycle)).
- **Python:** `pip install mcp` now yields 2.x (supports 2026-07-28 *and* every
  earlier revision); v1.x is maintained on a branch — pin `mcp>=1.28,<2` if not
  ready ([pypi.org/project/mcp/](https://pypi.org/project/mcp/), checked 2026-08-16).

## 5. What this means for mini-agent's MCP client, today

The safe bet: **a tools-only client on top of `mcp` 2.x**, designed around statelessness.

1. **Use the official Python SDK (`mcp>=2`), don't hand-roll the protocol.** It
   speaks 2026-07-28 and all earlier revisions, so era negotiation, headers, and the
   legacy handshake fallback come for free
   ([pypi.org/project/mcp/](https://pypi.org/project/mcp/)). Note it is asyncio-based;
   since mini-agent is synchronous, wrap each MCP operation in `asyncio.run()` (or one
   background event-loop thread) behind a small synchronous facade — per-request
   statelessness makes this wrapping natural.
2. **Tools-only is now the spec-blessed minimum.** Implement `tools/list` +
   `tools/call`. Skip Roots, Sampling, and Logging entirely — they're deprecated with
   documented migrations ([SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)).
   Skip resources/prompts until a real need appears; they're optional capabilities.
3. **Support both transports; treat stdio as primary for a local coding agent.**
   stdio remains fully supported in 2026-07-28 and is what local servers
   (filesystem, git, etc.) use. For remote servers, speak Streamable HTTP only —
   never implement the deprecated 2024 HTTP+SSE transport
   ([transport spec](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)).
4. **Design as if every call is independent.** Don't build abstractions around a
   connection lifecycle, session IDs, or server-initiated callbacks. Model each tool
   call as request→result, where a result may be `input_required` (MRTR) → gather
   input → retry. If you architect elicitation as "handle a server-initiated request
   mid-stream," v2 invalidates it; as "resolve an input_required result," both eras fit
   ([MRTR](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr)).
5. **Cache tool lists per server with a TTL.** Fetch `tools/list` once at startup,
   honor `ttlMs` when present, and keep tool ordering stable in the prompt — this is
   exactly what the spec now optimizes for prompt caching
   ([SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549)).
6. **Don't build code-execution tool surfacing yet — but don't preclude it.** Code
   Mode is a server-side or harness-side *pattern*, not a client protocol feature;
   servers like Cloudflare's expose it as two ordinary tools, which a plain
   tools-only client already handles ([code-mode-mcp](https://blog.cloudflare.com/code-mode-mcp/)).
   Client-side code mode requires a sandbox — out of scope for a minimal agent.
7. **Defer auth.** Start with no-auth/bearer-token servers (env-var token covers most
   real servers today). If OAuth comes later: CIMD first, DCR only as fallback, always
   validate `iss` (RFC 9207) and bind tokens to the server `resource` — the SDK
   implements this ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)).
8. **Ignore extensions (Tasks, MCP Apps, EMA) for now.** They're opt-in via the
   `extensions` capability field and default to absent
   ([extensions overview](https://modelcontextprotocol.io/docs/extensions/overview)).

Bottom line: the work that survives v2 is the boring core — spawn/connect, list
tools, inject schemas, call tools, return results. The work v2 killed is exactly
what a minimal client would have skipped anyway: session management, SSE
resumability, server-initiated request handling, DCR.

## Source index

- Cloudflare, "The next generation of MCP" (Matt Carey, 2026-08-06): https://blog.cloudflare.com/mcp-v2/
- MCP blog, "The 2026-07-28 Specification" (Soria Parra & Delimarsky, 2026-07-28): https://blog.modelcontextprotocol.io/posts/2026-07-28
- Official changelog: https://modelcontextprotocol.io/specification/2026-07-28/changelog
- Versioning & negotiation: https://modelcontextprotocol.io/specification/versioning
- Streamable HTTP transport (incl. backward compat): https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http
- MRTR pattern: https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr
- Feature lifecycle policy: https://modelcontextprotocol.io/community/feature-lifecycle
- MCP first anniversary / 2025-11-25 release: https://blog.modelcontextprotocol.io/posts/2025-11-25-first-mcp-anniversary/
- AAIF donation (2025-12-09): https://blog.modelcontextprotocol.io/posts/2025-12-09-mcp-joins-agentic-ai-foundation/ and https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation
- Cloudflare, "Code Mode: give agents an entire API in 1,000 tokens" (2026-02-20): https://blog.cloudflare.com/code-mode-mcp/
- Anthropic, "Code execution with MCP" (2025-11): https://www.anthropic.com/engineering/code-execution-with-mcp
- Python SDK on PyPI (`mcp` 2.0.0, 2026-07-28): https://pypi.org/project/mcp/
