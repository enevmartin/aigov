"""Atomic file-based task queue.

A task lives in exactly one of four state directories::

    tasks/pending/{task_id}/   # enqueued, waiting for a brain
    tasks/running/{task_id}/   # claimed by a brain
    tasks/done/{task_id}/      # brain finished; awaiting publish validation
    tasks/failed/{task_id}/    # rejected (with reason.txt) or crashed

Transitions use :func:`os.rename` on the task directory, which is atomic on
POSIX and on Windows/NTFS for same-volume moves — two workers racing to claim
the same task cannot both succeed.
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from core.contracts import TaskSpec

TASK_FILE = "task.yaml"
REASON_FILE = "reason.txt"


class QueueState:
    """The queue states (directory names under the queue root).

    ``REVIEW`` holds originals awaiting their second reading: the task
    finished (``done``), core moved it here and enqueued a review task;
    the verdict sends it back to ``done`` (approved) or ``pending``
    (revise) — see ``core/review.py``.
    """

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    REVIEW = "review"
    FAILED = "failed"

    ALL = (PENDING, RUNNING, DONE, REVIEW, FAILED)


class FileQueue:
    """Manage task directories across the four state directories."""

    def __init__(self, root: Path) -> None:
        """Create the queue rooted at *root* (e.g. ``repo/tasks``).

        All four state directories are created if missing.
        """
        self.root = root
        for state in QueueState.ALL:
            (root / state).mkdir(parents=True, exist_ok=True)

    # -- paths ------------------------------------------------------------

    def path(self, state: str, task_id: str) -> Path:
        """Return the directory for *task_id* in *state* (may not exist)."""
        if state not in QueueState.ALL:
            raise ValueError(f"unknown queue state: {state!r}")
        return self.root / state / task_id

    def state_of(self, task_id: str) -> str | None:
        """Return the state holding *task_id*, or ``None`` if absent."""
        for state in QueueState.ALL:
            if self.path(state, task_id).is_dir():
                return state
        return None

    # -- enqueue ----------------------------------------------------------

    def enqueue(self, spec: TaskSpec, input_files: dict[str, bytes] | None = None,
                expected_schema: str | None = None) -> Path:
        """Create a pending task directory from *spec* and return its path.

        The directory is built in a hidden staging name and atomically renamed
        into ``pending/`` so consumers never observe a half-written task.
        Raises ``FileExistsError`` if the task id already exists in any state.
        """
        if (existing := self.state_of(spec.id)) is not None:
            raise FileExistsError(f"task {spec.id!r} already exists in {existing}/")

        staging = self.root / QueueState.PENDING / f".staging-{spec.id}"
        if staging.exists():
            shutil.rmtree(staging)
        (staging / "input").mkdir(parents=True)

        task_yaml = yaml.safe_dump(
            spec.model_dump(mode="json", exclude_none=True), allow_unicode=True, sort_keys=False
        )
        (staging / TASK_FILE).write_text(task_yaml, encoding="utf-8")

        for name, content in (input_files or {}).items():
            target = staging / "input" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

        if expected_schema is not None:
            (staging / "expected.schema.json").write_text(expected_schema, encoding="utf-8")

        final = self.path(QueueState.PENDING, spec.id)
        os.rename(staging, final)
        return final

    # -- state transitions ------------------------------------------------

    def claim(self, task_id: str) -> Path:
        """Atomically move a pending task to ``running/`` and return its path.

        Touches ``task.yaml`` so staleness (``requeue_stale``) is measured
        from the CLAIM time, not from when the task was enqueued. Raises
        ``FileNotFoundError`` if the task is not pending (e.g. another worker
        won the race).
        """
        target = self.move(task_id, QueueState.PENDING, QueueState.RUNNING)
        os.utime(target / TASK_FILE, None)
        return target

    def release(self, task_id: str) -> Path:
        """Return a running task to ``pending/`` (retry in a later session)."""
        return self.move(task_id, QueueState.RUNNING, QueueState.PENDING)

    def complete(self, task_id: str) -> Path:
        """Move a running task to ``done/`` (brain finished writing output/)."""
        return self.move(task_id, QueueState.RUNNING, QueueState.DONE)

    def fail(self, task_id: str, reason: str, source_state: str = QueueState.RUNNING) -> Path:
        """Move a task to ``failed/`` and record *reason* in ``reason.txt``."""
        target = self.move(task_id, source_state, QueueState.FAILED)
        (target / REASON_FILE).write_text(reason, encoding="utf-8")
        return target

    def move(self, task_id: str, src: str, dst: str) -> Path:
        """Atomically move a task between states (building block for flows)."""
        source = self.path(src, task_id)
        if not source.is_dir():
            raise FileNotFoundError(f"task {task_id!r} not found in {src}/")
        target = self.path(dst, task_id)
        os.rename(source, target)
        return target

    # -- inspection -------------------------------------------------------

    def list_tasks(self, state: str) -> list[str]:
        """Return sorted task ids currently in *state* (staging dirs excluded)."""
        if state not in QueueState.ALL:
            raise ValueError(f"unknown queue state: {state!r}")
        directory = self.root / state
        return sorted(
            p.name for p in directory.iterdir() if p.is_dir() and not p.name.startswith(".")
        )

    def load_spec(self, state: str, task_id: str) -> TaskSpec:
        """Read and validate ``task.yaml`` for *task_id* in *state*."""
        raw = (self.path(state, task_id) / TASK_FILE).read_text(encoding="utf-8")
        return TaskSpec.model_validate(yaml.safe_load(raw))

    # -- recovery ---------------------------------------------------------

    def requeue_stale(self, older_than: timedelta) -> list[str]:
        """Return crashed tasks from ``running/`` back to ``pending/``.

        A task is stale when its ``task.yaml`` mtime is older than
        *older_than*. Returns the requeued task ids.
        """
        now = datetime.now(tz=UTC)
        requeued: list[str] = []
        for task_id in self.list_tasks(QueueState.RUNNING):
            marker = self.path(QueueState.RUNNING, task_id) / TASK_FILE
            if not marker.exists():
                continue
            age = now - datetime.fromtimestamp(marker.stat().st_mtime, tz=UTC)
            if age > older_than:
                self.move(task_id, QueueState.RUNNING, QueueState.PENDING)
                requeued.append(task_id)
        return requeued
