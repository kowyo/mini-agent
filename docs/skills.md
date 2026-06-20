# Skills

Skills are self-contained capability packages that the agent loads on-demand. When a task matches a skill's description, the agent reads the full instructions.

mini-agent follows the [Agent Skills](https://agentskills.io/specification) standard.

## Locations

- `~/.agents/skills/<name>/SKILL.md`
- `.agents/skills/<name>/SKILL.md`
- `.mini-agent/skills/<name>/SKILL.md`

Directories are scanned recursively. If the same skill name exists in both project skill directories, `.mini-agent/skills` takes precedence over `.agents/skills`.

## Variables

`${VARIABLE}` and `$VARIABLE` placeholders in `SKILL.md` are substituted at load time:

| Variable | Source |
|----------|--------|
| `MODEL_NAME` | Active model ID |
