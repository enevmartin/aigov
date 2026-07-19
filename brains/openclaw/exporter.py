"""Export a ministry as an OpenClaw AgentSkill package.

Real even though the openclaw runner is a skeleton: the export produces a
directory ready for ClawHub packaging, so a minister can be moved to an
OpenClaw orchestration today.
"""

from __future__ import annotations

import json
from pathlib import Path

from brains.common import load_declaration, load_prompts, persona_header
from core.config import AppConfig


def export_ministry(config: AppConfig, slug: str) -> list[Path]:
    """Write ``export/openclaw/{slug}/`` (skill.json + SKILL.md + prompts/)."""
    ministry_dir = config.ministry_dir(slug)
    declaration = load_declaration(ministry_dir)
    prompts = load_prompts(ministry_dir)

    package = config.root / "export" / "openclaw" / slug
    (package / "prompts").mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    manifest = {
        "name": f"aigov-{slug}-minister",
        "version": "1.0.0",
        "description": f"AI министър: {declaration['name']} (aigov.bg)",
        "language": "bg",
        "entry": "SKILL.md",
        "prompts": sorted(prompts),
        "contract": {
            "input": "task directory: task.yaml + input/ + expected.schema.json",
            "output": "output/report.md + output/aggregates.json (+ news.json)",
        },
    }
    manifest_path = package / "skill.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    written.append(manifest_path)

    skill_md = package / "SKILL.md"
    skill_md.write_text(
        f"{persona_header(declaration)}\n"
        "## Как работиш\n\n"
        "Получаваш директория на задача (task.yaml, input/, expected.schema.json)\n"
        "и записваш артефактите в output/ по договора на aigov. Конкретните\n"
        "инструкции за всеки тип задача са в prompts/.\n",
        encoding="utf-8",
    )
    written.append(skill_md)

    for name, text in prompts.items():
        prompt_path = package / "prompts" / name
        prompt_path.write_text(text, encoding="utf-8")
        written.append(prompt_path)
    return written
