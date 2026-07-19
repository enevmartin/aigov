"""Direct-API adapter skeleton (DeepSeek/Kimi later).

Unlike the CLI brains, this one will generate the artifacts itself from the
model's structured response and write them into ``output/`` — same contract,
different transport.
"""

from __future__ import annotations

from pathlib import Path

from brains.base import ArtifactSet, BrainAdapter
from core.config import AppConfig

_NOT_IMPLEMENTED = (
    "the api brain is a skeleton — see brains/api/README.md; "
    "set 'brain: claude_code' in config.yaml"
)


class ApiBrain:
    """:class:`BrainAdapter` placeholder for direct LLM API calls."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def run(self, task_dir: Path) -> ArtifactSet:
        """Not implemented yet — fails loudly instead of half-working."""
        raise NotImplementedError(_NOT_IMPLEMENTED)


def get_brain(config: AppConfig) -> BrainAdapter:
    """Composition-root hook (same shape as brains.claude_code)."""
    return ApiBrain(config)


def run_cabinet_session(
    config: AppConfig, brain: BrainAdapter | None = None, dry_run: bool = False
) -> dict[str, list[str]]:
    """Session entry point required of every brain package.

    ``--dry-run`` works even for a skeleton (it uses the fake brain).
    """
    from brains.claude_code.runner import run_cabinet_session as generic_session

    if dry_run:
        return generic_session(config, dry_run=True)
    raise NotImplementedError(_NOT_IMPLEMENTED)
