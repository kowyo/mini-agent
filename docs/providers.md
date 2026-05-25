# Providers

mini-agent supports any Anthropic-compatible endpoint.

| Variable | Auth Header | Use |
|---|---|---|
| `ANTHROPIC_API_KEY` | `x-api-key` | Anthropic API or compatible providers |
| `ANTHROPIC_AUTH_TOKEN` | `Authorization: Bearer` | Custom gateways (paired with `ANTHROPIC_BASE_URL`) |

## Environment Variables

```bash
# Anthropic API
export ANTHROPIC_API_KEY=sk-ant-api03-...

# Custom gateway
export ANTHROPIC_AUTH_TOKEN=...
export ANTHROPIC_BASE_URL=https://gateway.example.com
```


## Config File

Persist in `~/.mini-agent/.env`:

```bash
# Anthropic API
ANTHROPIC_API_KEY=sk-ant-api03-...

# Custom gateway
ANTHROPIC_AUTH_TOKEN=...
ANTHROPIC_BASE_URL=https://gateway.example.com
```

## Priority Order

1. Shell environment variables override `~/.mini-agent/.env`
2. `ANTHROPIC_API_KEY` takes priority over `ANTHROPIC_AUTH_TOKEN`
