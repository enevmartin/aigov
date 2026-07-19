"""Brain-agnostic cabinet-session loop with retry and resume semantics.

The loop claims every pending task and hands it to a runner chosen PER TASK
by the injected *resolver* — so two ministries can work on different brains
in one session. The core never imports any brain (чл. 1); the composition
root (``core/cli.py``) supplies a resolver that maps a brain name to a
concrete adapter, and tests inject fakes directly.

Failure semantics (никога не спира цяла):

- A task that fails is RETRIED once in a later session (released back to
  ``pending/`` with an attempt counter); the second failure moves it to
  ``failed/`` with the reason and raises a ``task_failed`` health event.
- A session that died mid-run leaves tasks in ``running/``; the next session
  reclaims them after the stale window (task-level checkpointing through the
  queue itself — no extra state).
- One bad task never affects the others.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Protocol

from core.config import AppConfig
from core.publish.health import record_event
from core.queue import FileQueue, QueueState

ATTEMPTS_FILE = "attempts.txt"
MAX_ATTEMPTS = 2  # first run + one retry
STALE_AFTER = timedelta(hours=2)


class TaskRunner(Protocol):
    """Structural twin of ``brains.base.BrainAdapter`` (no brains import)."""

    def run(self, task_dir: Path) -> object:  # noqa: D102 — protocol member
        ...


# brain name (from config) -> a runner for it
BrainResolver = Callable[[str], TaskRunner]


def _bump_attempts(task_dir: Path) -> int:
    """Increment and persist the attempt counter; return the new value."""
    marker = task_dir / ATTEMPTS_FILE
    attempts = int(marker.read_text(encoding="utf-8")) if marker.is_file() else 0
    attempts += 1
    marker.write_text(str(attempts), encoding="utf-8")
    return attempts


def _handle_failure(
    config: AppConfig,
    queue: FileQueue,
    task_id: str,
    ministry: str | None,
    reason: str,
    results: dict[str, list[str]],
) -> None:
    """Retry once; on the second failure park in failed/ and raise an alert."""
    attempts = _bump_attempts(queue.path(QueueState.RUNNING, task_id))
    if attempts < MAX_ATTEMPTS:
        queue.release(task_id)
        results["retried"].append(task_id)
        return
    queue.fail(task_id, reason)
    results["failed"].append(task_id)
    record_event(
        config,
        kind="task_failed",
        ministry=ministry,
        message=f"задача {task_id} се провали окончателно след {attempts} опита: {reason}",
    )


def run_session(config: AppConfig, resolver: BrainResolver) -> dict[str, list[str]]:
    """Process ALL pending tasks in one batch, resolving the brain per task.

    Starts by reclaiming tasks stranded in ``running/`` by a dead session
    (older than :data:`STALE_AFTER`). Returns ``{"done": [...], "failed":
    [...], "retried": [...], "resumed": [...]}`` — ``retried`` tasks are back
    in ``pending/`` for the NEXT session; ``resumed`` are stale tasks this
    session reclaimed and processed.
    """
    queue = FileQueue(config.path("tasks"))
    resumed = queue.requeue_stale(STALE_AFTER)
    results: dict[str, list[str]] = {
        "done": [],
        "failed": [],
        "retried": [],
        "resumed": resumed,
    }

    for task_id in queue.list_tasks(QueueState.PENDING):
        ministry: str | None = None
        try:
            spec = queue.load_spec(QueueState.PENDING, task_id)
            ministry = spec.ministry
            runner = resolver(config.brain_for(spec.ministry))
        except Exception as exc:  # noqa: BLE001 — unreadable spec/unknown brain
            queue.claim(task_id)
            _handle_failure(
                config, queue, task_id, ministry, f"{type(exc).__name__}: {exc}", results
            )
            continue

        running = queue.claim(task_id)
        try:
            runner.run(running)
        except Exception as exc:  # noqa: BLE001 — any brain failure fails only this task
            _handle_failure(
                config, queue, task_id, ministry, f"{type(exc).__name__}: {exc}", results
            )
        else:
            queue.complete(task_id)
            results["done"].append(task_id)
    return results
