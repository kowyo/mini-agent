# Plugins

mini-agent loads external plugins via the `mini_agent.plugins` [entry point](https://packaging.python.org/en/latest/guides/creating-and-discovering-plugins/) group.

## Interface

```python
from mini_agent import MiniAgentPlugin

class MyPlugin(MiniAgentPlugin):
    def on_session_start(self, session_id: str): ...
```

| Hook | When |
|------|------|
| `on_agent_init()` | Startup, before CLI loop |
| `on_session_start(session_id)` | New session, `/new`, `/resume` |
| `on_turn_complete(session_id, history, round_usages)` | After each assistant response saved |
| `on_session_end(session_id, history, round_usages)` | Interactive loop exits |

## Creating a Plugin

```toml
[project.entry-points."mini_agent.plugins"]
my-plugin = "my_plugin.plugin:create_plugin"
```

```python
# src/my_plugin/plugin.py
from mini_agent import MiniAgentPlugin

class MyPlugin(MiniAgentPlugin):
    def on_session_start(self, session_id: str) -> None:
        print(f"Session started: {session_id}")

def create_plugin():
    return MyPlugin()
```

```bash
pip install my-plugin
```

## Secrets

Plugins can store API keys in `~/.mini-agent/.env` (loaded automatically). Shell env vars take precedence.

```bash
# ~/.mini-agent/.env
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```
