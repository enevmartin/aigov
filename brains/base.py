"""The brain port: one protocol every adapter implements.

A brain receives a claimed task directory (``tasks/running/{id}/`` with
``task.yaml``, ``input/``, ``expected.schema.json``), does its work, and
writes the artifacts into ``{task_dir}/output/``. It never touches the queue,
never writes to ``published/``, and never talks to the core except through
these files — that is what makes brains swappable with a one-line config
change.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

OUTPUT_DIR = "output"
REPORT_FILE = "report.md"


@dataclass(frozen=True)
class ArtifactSet:
    """Paths of the artifacts a brain produced for one task.

    Contract v2 (чл. 8): a brain writes prose (``report.md``) or a verdict /
    aggregate count (``review.json``, ``signals.json``) — never numbers for
    the dashboard. Validation and publishing are the core's job.
    """

    report: Path | None
    files: tuple[Path, ...] = ()

    @classmethod
    def from_output_dir(cls, output_dir: Path) -> ArtifactSet:
        """Build the set from a conventional ``output/`` directory layout."""
        report = output_dir / REPORT_FILE
        files = tuple(sorted(p for p in output_dir.iterdir() if p.is_file()))
        return cls(report=report if report.exists() else None, files=files)


@runtime_checkable
class BrainAdapter(Protocol):
    """The port. Adapters implement exactly one method."""

    def run(self, task_dir: Path) -> ArtifactSet:
        """Process the task in *task_dir* and return the produced artifacts.

        Must write all artifacts under ``{task_dir}/output/``. Raise an
        exception to signal failure — the caller (a cabinet-session driver in
        the adapter's package, or the CLI) moves the task to ``failed/``.
        """
        ...
