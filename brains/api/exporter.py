"""Export a ministry as a direct-API artifact: system prompt + tools JSON.

Real even though the api runner is a skeleton: the export gives any
chat-completions runtime everything it needs to host the minister.
"""

from __future__ import annotations

import json
from pathlib import Path

from brains.common import load_declaration, load_prompts, persona_header
from core.config import AppConfig

# The structured outputs the model must produce, described as tools so any
# tool-calling API can enforce the contract shape.
_TOOLS = [
    {
        "name": "write_report",
        "description": "Запиши отчета (report.md): front-matter + анализ на български",
        "parameters": {
            "type": "object",
            "properties": {
                "ministry": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "sources": {"type": "array", "items": {"type": "object"}},
                "body_markdown": {"type": "string"},
            },
            "required": ["ministry", "date", "title", "summary", "sources", "body_markdown"],
        },
    },
    {
        "name": "write_aggregates",
        "description": "Запиши числата за дашборда (aggregates.json)",
        "parameters": {
            "type": "object",
            "properties": {
                "ministry": {"type": "string"},
                "date": {"type": "string"},
                "series": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["ministry", "date", "series"],
        },
    },
    {
        "name": "write_news",
        "description": "Запиши новинарския дайджест (news.json, само за news_digest)",
        "parameters": {
            "type": "object",
            "properties": {
                "ministry": {"type": "string"},
                "date": {"type": "string"},
                "items": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["ministry", "date", "items"],
        },
    },
]


def export_ministry(config: AppConfig, slug: str) -> list[Path]:
    """Write ``export/api/{slug}.json`` and return the written paths."""
    ministry_dir = config.ministry_dir(slug)
    declaration = load_declaration(ministry_dir)
    prompts = load_prompts(ministry_dir)

    sections = "\n\n".join(
        f"## Инструкции: {name}\n\n{text}" for name, text in prompts.items()
    )
    api_settings = config.brains.get("api", {})
    artifact = {
        "name": f"aigov-{slug}-minister",
        "model": api_settings.get("model"),
        "fallback": api_settings.get("fallback"),
        "system_prompt": f"{persona_header(declaration)}\n{sections}",
        "tools": _TOOLS,
    }

    target = config.root / "export" / "api" / f"{slug}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return [target]
