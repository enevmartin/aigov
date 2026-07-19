"""Load and validate ``config.yaml`` — the single switching point of the system.

The ``brain`` key selects the adapter; nothing else in the core changes when
it flips. Paths are resolved relative to the repo root so every component
agrees on where the queue, staging and published artifacts live.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

CONFIG_FILE = "config.yaml"


class PathsConfig(BaseModel):
    """Relative locations of the working directories (see config.yaml)."""

    model_config = ConfigDict(extra="forbid")

    tasks: str = "tasks"
    published: str = "published"
    data_raw: str = "data/raw"
    data_staging: str = "data/staging"
    ministries: str = "ministries"


class AppConfig(BaseModel):
    """Validated view of ``config.yaml``.

    ``brains`` is deliberately loose (``dict``): each adapter defines its own
    settings and the core never interprets them — invariant #1.
    """

    model_config = ConfigDict(extra="forbid")

    brain: str = Field(min_length=1)
    brains: dict[str, dict[str, object]] = Field(default_factory=dict)
    ministries: list[str] = Field(min_length=1)
    schedules: dict[str, str] = Field(default_factory=dict)
    paths: PathsConfig = Field(default_factory=PathsConfig)

    # Set by load_config(); excluded from the schema.
    root: Path = Field(default=Path("."), exclude=True)

    def path(self, name: str) -> Path:
        """Resolve a configured path (``tasks``, ``published``, …) to absolute."""
        rel: str = getattr(self.paths, name)
        return self.root / rel

    def ministry_dir(self, slug: str) -> Path:
        """Directory of one ministry's declarations (yaml + prompts)."""
        return self.path("ministries") / slug


def load_config(root: Path) -> AppConfig:
    """Read ``{root}/config.yaml`` and return the validated configuration."""
    raw = (root / CONFIG_FILE).read_text(encoding="utf-8")
    config = AppConfig.model_validate(yaml.safe_load(raw))
    config.root = root
    return config
