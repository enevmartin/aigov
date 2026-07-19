"""Export a ministry as a Claude Code subagent definition.

``aigov export --ministry <slug> --brain claude_code`` writes
``.claude/agents/<slug>.md`` — a self-contained subagent whose system prompt
is composed from the ministry declaration. The definition carries everything;
moving the minister to another Claude Code checkout is copying one file.
"""

from __future__ import annotations

from pathlib import Path

from brains.claude_code.runner import CONTRACT_INSTRUCTIONS
from brains.common import load_declaration, load_prompts, persona_header
from core.config import AppConfig


def export_ministry(config: AppConfig, slug: str) -> list[Path]:
    """Write ``.claude/agents/{slug}.md`` and return the written paths."""
    ministry_dir = config.ministry_dir(slug)
    declaration = load_declaration(ministry_dir)
    prompts = load_prompts(ministry_dir)

    sections = "\n\n".join(
        f"## Инструкции: {name}\n\n{text}" for name, text in prompts.items()
    )
    body = (
        f"{persona_header(declaration)}\n"
        f"{sections}\n\n"
        f"{CONTRACT_INSTRUCTIONS}"
    )
    description = (
        f"AI министър: {declaration['name']} — анализи, отчети и новинарски "
        f"дайджести на български по файловия договор на aigov"
    )
    frontmatter = (
        f"---\nname: {slug}-minister\ndescription: {description}\n---\n\n"
    )

    target = config.root / ".claude" / "agents" / f"{slug}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(frontmatter + body, encoding="utf-8")
    return [target]
