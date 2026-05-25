# Config

Config stored in `~/.mini-agent/config.toml`.

| Key | Default | Values |
|---|---|---|
| `model_id` | `claude-sonnet-4-6` | Any model ID from `/v1/models` |
| `reasoning_effort` | `high` | `disabled`, `adaptive`, `low`, `medium`, `high`, `xhigh`, `max` |

## Example

```toml
model_id = "claude-sonnet-4-6"
reasoning_effort = "high"
```
