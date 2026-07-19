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
AGGREGATES_FILE = "aggregates.json"
NEWS_FILE = "news.json"


@dataclass(frozen=True)
class ArtifactSet:
    """Paths of the artifacts a brain produced for one task.

    ``news`` is ``None`` unless the task type calls for a digest. Paths point
    inside ``{task_dir}/output/``; validation and publishing are the core's
    job (``core/publish``), never the brain's.
    """

    report: Path
    aggregates: Path
    news: Path | None = None

    @classmethod
    def from_output_dir(cls, output_dir: Path) -> ArtifactSet:
        """Build the set from a conventional ``output/`` directory layout."""
        news = output_dir / NEWS_FILE
        return cls(
            report=output_dir / REPORT_FILE,
            aggregates=output_dir / AGGREGATES_FILE,
            news=news if news.exists() else None,
        )


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
