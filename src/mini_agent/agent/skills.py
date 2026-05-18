import re
from pathlib import Path
from string import Template
from typing import Any

import yaml

from ..config import SKILLS_DIRS, config


class SkillLoader:
    def __init__(self, skills_dirs: list[Path]) -> None:
        self.skills_dirs = skills_dirs
        self.skills: dict[str, dict[str, Any]] = {}
        self._load_all()

    def _variables(self) -> dict[str, str]:
        return {"MODEL_NAME": config.get_model()}

    def _load_all(self) -> None:
        vars = self._variables()
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
                meta["description"] = Template(description).safe_substitute(vars)
                self.skills[name] = {
                    "meta": meta,
                    "body": Template(body).safe_substitute(vars),
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
        lines = []
        for name, skill in self.skills.items():
            lines.append(f"- {name}: {skill['meta']['description']}")
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        skill = self.skills.get(name)
        if not skill:
            return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
        return f'<skill_content name="{name}">\n{skill["body"]}\n</skill_content>'


skill_loader = SkillLoader(SKILLS_DIRS)
