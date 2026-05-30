# Config

Config stored in `~/.mini-agent/config.toml`.

| Key | Default | Values |
|---|---|---|
| `model_id` | `claude-sonnet-4-6` | Any model ID from `/v1/models` |
| `reasoning_effort` | `high` | `disabled`, `adaptive`, `low`, `medium`, `high`, `xhigh`, `max` |
| `provider` | *(none)* | Any provider ID from [models.dev](https://models.dev/) |

## Example

```toml
provider = "openrouter"
model_id = "gemini-3.5-flash"
reasoning_effort = "high"
```

## Behavior

- `/model` in interactive mode saves to config.toml permanently.
- The file is read on startup. Created automatically when you first run `/model`.
- `provider` is optional. If specified, `mini-agent` searches for model metadata under this provider inside [models.dev](https://models.dev/) first. If not found or omitted, it falls back to prefix matching, then searches all providers.

  | Default Provider | Model ID Prefixes |
  |---|---|
  | `anthropic` | `claude-` |
  | `deepseek` | `deepseek-` |
  | `google` | `gemini-` |
  | `openai` | `gpt-`, `o3`, `o4`, `text-`, `chatgpt-` |
