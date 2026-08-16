# MCP

Connect [MCP](https://modelcontextprotocol.io) servers to give the agent extra tools.
Configured servers connect at startup; their tools appear to the model as
`mcp__<server>__<tool>` alongside the built-in tools.

## Config

Servers are read from `~/.mini-agent/mcp.json` (all projects) and
`<cwd>/.mini-agent/mcp.json` (current project). Both files use the standard
`mcpServers` format, so config snippets from server READMEs work unchanged.
When both files define the same server name, the project entry wins. Config
changes take effect on the next start.

```json
{
  "mcpServers": {
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp"]
    },
    "github": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/"
    }
  }
}
```

| Key | Applies to | Meaning |
|---|---|---|
| `command` | stdio | Executable to launch (an entry without `type` is stdio) |
| `args` | stdio | Command arguments (default `[]`) |
| `env` | stdio | Extra environment variables, merged over a minimal default environment |
| `type` | http | `"http"` for Streamable HTTP servers |
| `url` | http | The server's endpoint URL |
| `headers` | http | Request headers, e.g. a bearer token |
| `client_id` | http | Pre-registered OAuth client ID; without it, servers self-register or use the built-in GitHub client |
| `client_secret` | http | Client secret for the pre-registered OAuth client |
| `timeout` | both | Seconds per tool call (default `60`) |

`${VAR}` in `env`, `url`, `headers`, `client_id`, and `client_secret` expands
from the environment (including `~/.mini-agent/.env`), so tokens stay out of
checked-in files.

## Behavior

- `/mcp` opens a picker over all servers: select a pending one to authorize
  it, a failed one to retry, or a connected one to list its tools.
- `/status` lists each server with its tools, failure reason, or pending
  authorization. A failed server is skipped and the session continues.
- Servers have 10 seconds to start (5 minutes when authorizing). Tool calls
  time out after the configured `timeout` and return an error result to the
  model.
- If a server crashes mid-session, its next tool call returns an error
  result and the server is disabled; other servers keep working.
- Tool results support text and images; output is truncated past
  50,000 characters.

## Troubleshooting

- **Server fails to start**: run the `command` with its `args` in a
  terminal to see its logs — server stderr is discarded when run by
  mini-agent. Anything the server prints to stdout that isn't protocol
  traffic breaks the connection.
- **`did not start within 10s`**: first runs of `npx`/`uvx` servers may
  download packages; run the command once manually and retry.
- **`authorization required` keeps coming back**: the stored token may be
  revoked or expired beyond refresh — delete
  `~/.mini-agent/mcp-auth/<server>.json` and authorize again via `/mcp`.
- **Two servers expose the same tool name**: the namespaced names stay
  distinct (`mcp__a__search`, `mcp__b__search`), so no action is needed.
