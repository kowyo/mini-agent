# Providers

mini-agent supports ChatGPT account authentication and any Anthropic-compatible endpoint. Define each endpoint
as a provider in `~/.mini-agent/config.toml` and pick the active one with
`provider`.

```toml
provider = "deepseek"

[providers.colorist]
name = "Colorist Staging"
base_url = "https://colorist.example.com"
api_key_env = "COLORIST_API_KEY"

[providers.deepseek]
name = "DeepSeek"
base_url = "https://api.deepseek.com/anthropic"
api_key_env = "DEEPSEEK_API_KEY"
```

| Field | Description |
|---|---|
| `[providers.<id>]` | Provider ID used by `provider` and `--provider` |
| `name` | Display name shown in `/provider` and `/status` |
| `base_url` | Anthropic-compatible API base URL |
| `api_key_env` | Environment variable holding the API key |

Keep every key in `~/.mini-agent/.env`:

```bash
COLORIST_API_KEY=...
DEEPSEEK_API_KEY=...
```

The key is sent as `Authorization: Bearer <key>`. Shell environment
variables override `~/.mini-agent/.env`.

## ChatGPT

Run `mini /login` (or `/login` inside a session) to authorize a ChatGPT account
using a browser verification URL and device code. On success, mini-agent selects
the built-in `chatgpt` provider and `gpt-5.4`. No `[providers.chatgpt]` table or
API key is needed. Existing API-key providers remain available.

`/model` offers `gpt-5.4` and manual model-ID entry, without querying an
Anthropic models endpoint. Model availability depends on your account; see
[OpenAI's Codex models](https://developers.openai.com/codex/models/).

Run `mini /logout` or `/logout` to delete only mini-agent's locally stored
ChatGPT credentials. It leaves the selected provider/model and other apps'
authentication files unchanged. Log in again or choose an API-key provider to
continue. Credentials are stored in `~/.mini-agent/chatgpt-auth.json`, with
owner-only permissions on POSIX, and refreshed automatically before expiry.
Treat this file as a secret and never commit it. A local lock serializes token
rotation across processes; after a killed process, remove
`~/.mini-agent/chatgpt-auth.lock` only when no mini-agent process is running.

Device authorization must be enabled for your account; subscription limits and
model availability still apply. Login uses the Codex device authorization flow,
following [agent-foundation](https://github.com/converge-ai-labs/agent-foundation).

## Switching

- `/provider` picks a provider and saves it to `config.toml`.
- `mini --provider <id>` uses a provider for the current session only.
- When `provider` is unset, the first provider in `config.toml` is used.

Except for a successful `/login`, the model stays the same when you switch providers; run `/model` to pick one
the new provider serves.

With no configured API-key providers and no explicit ChatGPT selection, startup
continues to report missing providers. Use `mini /login` to set up ChatGPT.
