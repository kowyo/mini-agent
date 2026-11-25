# Usage

## CLI

```bash
mini [options] [prompt]
mini update
```

| Flag | Description |
|------|-------------|
| default | Interactive mode |
| `-p`, `--print` | Print response and exit; also reads piped stdin |
| `-m`, `--model` | Model for the current session |
| `--provider` | Provider ID from `config.toml` for the current session |
| `-e`, `--effort` | Reasoning effort: `disabled`, `adaptive`, `low`, `medium`, `high`, `xhigh`, `max` |
| `-r`, `--resume [id]` | Resume a session by ID, or latest if no ID |
| `-v`, `--version` | Show version |
| `update` | Update to the latest release |

> [!NOTE]
> `--model`, `--effort`, and `--provider` override for the current session only.

### Example

```bash
# Non-interactive with piped stdin
cat README.md | mini -p "Summarize this"

# Resume most recent session
mini -r

# Custom model and effort
mini -m claude-opus-4-1 -e high

# Another provider for this session
mini --provider deepseek -m deepseek-v4-flash

# Interactive with initial prompt
mini "Refactor this file"

# Update to the latest release
mini update

# Jump to slash command
mini /model
mini /resume
```

## Interactive Commands

| Command | Description |
|---------|-------------|
| `/model` | Switch model and reasoning effort |
| `/provider` | Switch provider |
| `/status` | Show provider, model, session, tokens, and context window |
| `/new` | Start a new session |
| `/resume` | Pick from previous sessions |
| `/copy` | Copy last assistant message to clipboard |
| `/compact [focus]` | Summarize the conversation into a fresh context, optionally focusing the summary |
| `/mcp` | Authorize and list MCP servers |
| `/exit`, `q` | Quit |

When the context window fills up, mini-agent compacts the conversation automatically: it replaces the earlier messages with a structured summary and continues from it. Run `/compact` yourself at a task boundary to reset the context early, or pass a focus such as `/compact the parser refactor` to steer what the summary keeps.

To compact at a fixed token count instead of near the model's limit, set `auto_compact_threshold` in `~/.mini-agent/config.toml`:

```toml
auto_compact_threshold = 400000
```

The value is clamped below the context limit so the next request still fits, and `/status` shows the effective compaction point next to the context window.

## Keyboard Shortcuts

| Shortcut | Description |
|----------|-------------|
| <kbd>Ctrl</kbd>+<kbd>O</kbd> | Toggle full tool output and redraw the transcript |
| <kbd>Ctrl</kbd>+<kbd>V</kbd> | Paste image from clipboard |
| <kbd>Esc</kbd>+<kbd>Enter</kbd> / <kbd>Meta</kbd>+<kbd>Enter</kbd> | Insert newline |

## Context Files

mini-agent loads `AGENTS.md` at startup from:

- `~/.mini-agent/AGENTS.md` for global instructions
- parent directories, walking up from the current working directory
- the current directory

Use context files for project conventions, commands, and preferences.

`${VARIABLE}` and `$VARIABLE` placeholders in `AGENTS.md` are substituted at load time. `MODEL_NAME` resolves to the active model ID.
