"""Shared helpers for brain adapters and exporters.

Everything here is declaration-driven (reads ``ministries/{slug}/``) and
provider-free; the provider-specific shaping happens in each brain's own
``exporter.py``/runner.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml


def load_declaration(ministry_dir: Path) -> dict[str, Any]:
    """Read and parse ``ministry.yaml`` for a ministry."""
    raw = (ministry_dir / "ministry.yaml").read_text(encoding="utf-8")
    return cast("dict[str, Any]", yaml.safe_load(raw))


def load_prompts(ministry_dir: Path) -> dict[str, str]:
    """All prompt files of a ministry, keyed by file name."""
    prompts_dir = ministry_dir / "prompts"
    return {
        p.name: p.read_text(encoding="utf-8") for p in sorted(prompts_dir.glob("*.md"))
    }


def persona_header(declaration: dict[str, Any]) -> str:
    """The Bulgarian persona block shared by every export format."""
    persona = declaration.get("minister_persona", {})
    lines = "".join(f"- {k}: {v}\n" for k, v in persona.items())
    guardrails = "".join(f"- {rule}\n" for rule in declaration.get("guardrails", []))
    return (
        f"# {declaration['name']}\n\n"
        f"Ти си AI министърът на това министерство.\n{lines}\n"
        f"## Правни предпазители (ненарушими)\n\n{guardrails}"
    )
