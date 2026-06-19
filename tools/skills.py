"""Skill loader and runner.

Loads `*.md` files from skills/ directory at startup and exposes them as a single
`use_skill(name, vars)` tool to the agent. Each skill file has a `## TEMPLATE` section
whose body is the prompt template with `{placeholder}` variables.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_TEMPLATE_RE = re.compile(r"##\s+TEMPLATE\s*\n(.+)", re.DOTALL | re.IGNORECASE)


def _parse_skill(path: Path) -> dict[str, str] | None:
    text = path.read_text(encoding="utf-8")
    m = _TEMPLATE_RE.search(text)
    if not m:
        return None
    name = path.stem
    template = m.group(1).strip()
    # Description = first paragraph after the title
    desc = ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("USE WHEN"):
            desc = line.replace("USE WHEN:", "").strip()
            break
    return {"name": name, "description": desc, "template": template, "path": str(path)}


class SkillRegistry:
    name = "use_skill"
    description = (
        "Invoke a named skill (predefined prompt template) with variable substitutions. "
        "Skills are listed in skills/."
    )

    def __init__(self, llm, skills_dir: str = "skills") -> None:
        self.llm = llm
        self.skills_dir = Path(skills_dir)
        self.skills: dict[str, dict[str, str]] = {}
        self.load()

    def load(self) -> None:
        self.skills.clear()
        if not self.skills_dir.exists():
            return
        for md in self.skills_dir.glob("*.md"):
            if md.name.lower() == "readme.md":
                continue
            parsed = _parse_skill(md)
            if parsed:
                self.skills[parsed["name"]] = parsed
        log.info("Loaded %d skills: %s", len(self.skills), ", ".join(self.skills))

    def list_skills(self) -> list[dict[str, str]]:
        return [
            {"name": s["name"], "description": s["description"]}
            for s in self.skills.values()
        ]

    def run(self, name: str, vars: dict[str, Any] | None = None, json_mode: bool = False) -> str:
        if name not in self.skills:
            return f"ERROR: skill '{name}' not found. Available: {list(self.skills)}"
        template = self.skills[name]["template"]
        vars = vars or {}
        try:
            prompt = template.format(**vars)
        except KeyError as e:
            return f"ERROR: missing variable {e} for skill '{name}'"
        if json_mode:
            return str(self.llm.generate_json(prompt))
        return self.llm.generate(prompt, temperature=0.3)
