import re
from pathlib import Path
from typing import Any

import yaml

from ..config import SKILLS_DIRS, config

_VAR_RE = re.compile(r"\$([A-Z_][A-Z0-9_]*|\{[A-Z_][A-Z0-9_]*\})")


class SkillLoader:
    def __init__(self, skills_dirs: list[Path]) -> None:
        self.skills_dirs = skills_dirs
        self.skills: dict[str, dict[str, Any]] = {}
        self._load_all()

    def _variables(self) -> dict[str, str]:
        return {"MODEL_NAME": config.get_model()}

    @staticmethod
    def _substitute(text: str, variables: dict[str, str]) -> str:
        def repl(m: re.Match) -> str:
            key = m.group(1)
            if key.startswith("{") and key.endswith("}"):
                key = key[1:-1]
            return variables.get(key, m.group(0))

        return _VAR_RE.sub(repl, text)

    def _load_all(self) -> None:
        for skills_dir in self.skills_dirs:
            if not skills_dir.exists():
                continue
            for f in sorted(skills_dir.rglob("SKILL.md")):
                text = f.read_text()
                meta, body = self._parse_frontmatter(text)
                name = str(meta.get("name", "")).strip()
                description = str(meta.get("description", "")).strip()
                if not name or not description:
                    continue
                self.skills[name] = {
                    "meta": meta,
                    "description": description,
                    "body": body,
                    "path": str(f),
                }

    def _parse_frontmatter(self, text: str) -> tuple[dict[str, Any], str]:
        match = re.match(r"^---\n(.*?)\n---\n?(.*)", text, re.DOTALL)
        if not match:
            return {}, text

        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        return meta, match.group(2).strip()

    def get_descriptions(self) -> str:
        if not self.skills:
            return "(no skills available)"
        variables = self._variables()
        lines = [
            "<available_skills>",
            "  <instructions>The following skills provide specialized instructions for specific tasks. When a task matches a skill's description, call the activate_skill tool with the skill's name to load its full instructions.</instructions>",
        ]
        for name, skill in self.skills.items():
            desc = self._substitute(skill["description"], variables)
            lines.append("  <skill>")
            lines.append(f"    <name>{name}</name>")
            lines.append(f"    <description>{desc}</description>")
            lines.append(f"    <location>{skill['path']}</location>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        skill = self.skills.get(name)
        if not skill:
            return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
        variables = self._variables()
        body = self._substitute(skill["body"], variables)
        return f'<skill_content name="{name}">\n{body}\n</skill_content>'


skill_loader = SkillLoader(SKILLS_DIRS)
