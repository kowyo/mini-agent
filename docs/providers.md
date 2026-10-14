# Providers

mini-agent supports any Anthropic-compatible endpoint. Define each endpoint
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

## Switching

- `/provider` picks a provider and saves it to `config.toml`.
- `mini --provider <id>` uses a provider for the current session only.
- When `provider` is unset, the first provider in `config.toml` is used.

The model stays the same when you switch providers; run `/model` to pick one
the new provider serves.
