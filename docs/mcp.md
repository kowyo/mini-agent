# MCP

Connect [MCP](https://modelcontextprotocol.io) servers to give the agent extra tools.
Configured servers connect at startup; their tools appear to the model as
`mcp__<server>__<tool>` alongside the built-in tools.

## Config

Servers are read from `~/.mini-agent/mcp.json` (all projects) and
`<cwd>/.mini-agent/mcp.json` (current project). Both files use the standard
`mcpServers` format, so config snippets from server READMEs work unchanged.
When both files define the same server name, the project entry wins.

```json
{
  "mcpServers": {
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp"]
    },
    "github": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": {"Authorization": "Bearer ${GITHUB_PAT}"}
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
| `timeout` | both | Seconds per tool call (default `60`) |

`${VAR}` in `env`, `url`, and `headers` expands from the environment
(including `~/.mini-agent/.env`), so tokens stay out of checked-in files.
An unset variable is left as-is.

## Behavior

- A `mcp: connected <name> (N tools)` line prints per server at startup;
  a server that fails to start is reported and skipped, and the session
  continues without it.
- Servers have 10 seconds to start. Tool calls time out after the
  configured `timeout` and return an error result to the model.
- If a server crashes mid-session, its next tool call returns an error
  result and the server is disabled; other servers keep working.
- Tool results support text and images; output is truncated past
  50,000 characters.

## Troubleshooting

- **Server fails to start**: run the `command` with its `args` in a
  terminal. Anything the server prints to stdout that isn't protocol
  traffic breaks the connection; its stderr passes through to yours.
- **`did not start within 10s`**: first runs of `npx`/`uvx` servers may
  download packages; run the command once manually and retry.
- **Two servers expose the same tool name**: the namespaced names stay
  distinct (`mcp__a__search`, `mcp__b__search`), so no action is needed.
