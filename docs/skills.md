# Skills

Skills are loaded from `~/.agents/skills/<name>/SKILL.md` and `.agents/skills/<name>/SKILL.md`.

## Variables

SKILL.md files can use `${VARIABLE}` placeholders. They are substituted at load time.

| Variable | Source |
|----------|--------|
| `MODEL_NAME` | The active model ID (e.g. `claude-sonnet-4-6`) |
