# Providers

mini-agent talks to the model through one of two wire protocols, selected by the
`provider` key in `~/.mini-agent/config.toml`:

| `provider` | Protocol | Default endpoint |
|---|---|---|
| `anthropic-messages` (default) | Anthropic Messages API | `https://api.anthropic.com` |
| `openai-responses` | OpenAI Responses API | `https://api.openai.com/v1` |

## anthropic-messages

Supports any Anthropic-compatible endpoint. `reasoning_effort` accepts
`disabled`, `adaptive`, `low`, `medium`, `high`, `xhigh`, `max`.

| Variable | Auth Header | Use |
|---|---|---|
| `ANTHROPIC_API_KEY` | `x-api-key` | Anthropic API or compatible providers |
| `ANTHROPIC_AUTH_TOKEN` | `Authorization: Bearer` | Custom gateways (paired with `ANTHROPIC_BASE_URL`) |

## openai-responses

| Variable | Use |
|---|---|
| `OPENAI_API_KEY` | Bearer credential |
| `OPENAI_BASE_URL` | Override the API base URL |

Requests always set `store=false` and send the full conversation history.
`reasoning_effort` is passed through as `reasoning.effort` unchanged, so this
provider only accepts OpenAI's own values: `none`, `minimal`, `low`, `medium`,
`high`, `xhigh`, `max`. A detailed reasoning summary is requested so thinking
is shown. `cache_control` and the derived max-output token limit do not apply
to this provider.

## Config File

`~/.mini-agent/config.toml`:

```toml
provider = "anthropic-messages"

model_id = "claude-sonnet-4-6"
reasoning_effort = "high"
```

Credentials go in `~/.mini-agent/.env`:

```bash
# Anthropic
ANTHROPIC_API_KEY=sk-ant-api03-...

# Anthropic-compatible gateway
ANTHROPIC_AUTH_TOKEN=...
ANTHROPIC_BASE_URL=https://gateway.example.com

# OpenAI Responses
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
```

## Priority Order

1. Shell environment variables override `~/.mini-agent/.env`
2. `ANTHROPIC_API_KEY` takes priority over `ANTHROPIC_AUTH_TOKEN`
