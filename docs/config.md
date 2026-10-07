# Config

Config stored in `~/.mini-agent/config.toml`. MCP servers are configured
separately in `mcp.json` — see [mcp.md](mcp.md).

| Key | Default | Values |
|---|---|---|
| `provider` | `anthropic-messages` | `anthropic-messages`, `openai-responses` |
| `model_id` | `claude-sonnet-4-6` | Any model ID from `/v1/models` |
| `reasoning_effort` | `high` | Depends on `provider` — see [providers.md](providers.md) |
| `cache_control` | `false` | `true`, `false` |

## Example

```toml
provider = "anthropic-messages"
model_id = "gemini-3.5-flash"
reasoning_effort = "high"
cache_control = true
```

See [providers.md](providers.md) for the environment variables each provider uses.

## Behavior

- `/model` in interactive mode saves to config.toml permanently.
- The file is read on startup. Created automatically when you first run `/model`.
- `cache_control` — When set to `true`, sends an [ephemeral cache control](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) directive on every message, enabling prompt caching where the API supports it. Defaults to `false`. Typically only useful with Anthropic Claude models.
