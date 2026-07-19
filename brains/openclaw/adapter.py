"""OpenClaw adapter skeleton — the contract is fixed, the transport is not.

Everything the future implementation must do is already specified by
:class:`brains.base.BrainAdapter` and the file-based task contract; only the
gateway plumbing is missing.
"""

from __future__ import annotations

from pathlib import Path

from brains.base import ArtifactSet, BrainAdapter
from core.config import AppConfig

_NOT_IMPLEMENTED = (
    "the openclaw brain is a skeleton — see brains/openclaw/README.md; "
    "set 'brain: claude_code' in config.yaml"
)


class OpenClawBrain:
    """:class:`BrainAdapter` placeholder for the OpenClaw gateway."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def run(self, task_dir: Path) -> ArtifactSet:
        """Not implemented yet — fails loudly instead of half-working."""
        raise NotImplementedError(_NOT_IMPLEMENTED)


def get_brain(config: AppConfig) -> BrainAdapter:
    """Composition-root hook (same shape as brains.claude_code)."""
    return OpenClawBrain(config)


def run_cabinet_session(
    config: AppConfig, brain: BrainAdapter | None = None, dry_run: bool = False
) -> dict[str, list[str]]:
    """Session entry point required of every brain package.

    ``--dry-run`` works even for a skeleton (it uses the fake brain), so the
    pipeline can be rehearsed before the adapter exists.
    """
    from brains.claude_code.runner import run_cabinet_session as generic_session

    if dry_run:
        return generic_session(config, dry_run=True)
    raise NotImplementedError(_NOT_IMPLEMENTED)
