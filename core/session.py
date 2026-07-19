"""Brain-agnostic cabinet-session loop.

The loop claims every pending task and hands it to a runner chosen PER TASK
by the injected *resolver* — so two ministries can work on different brains
in one session. The core never imports any brain (чл. 1); the composition
root (``core/cli.py``) supplies a resolver that maps a brain name to a
concrete adapter, and tests inject fakes directly.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from core.config import AppConfig
from core.queue import FileQueue, QueueState


class TaskRunner(Protocol):
    """Structural twin of ``brains.base.BrainAdapter`` (no brains import)."""

    def run(self, task_dir: Path) -> object:  # noqa: D102 — protocol member
        ...


# brain name (from config) -> a runner for it
BrainResolver = Callable[[str], TaskRunner]


def run_session(config: AppConfig, resolver: BrainResolver) -> dict[str, list[str]]:
    """Process ALL pending tasks in one batch, resolving the brain per task.

    Each task's brain comes from ``config.brain_for(task.ministry)``. One
    failing task moves to ``failed/`` with a reason and never stops the rest
    (чл. 7). Returns ``{"done": [...ids], "failed": [...ids]}``.
    """
    queue = FileQueue(config.path("tasks"))
    results: dict[str, list[str]] = {"done": [], "failed": []}
    for task_id in queue.list_tasks(QueueState.PENDING):
        try:
            spec = queue.load_spec(QueueState.PENDING, task_id)
            runner = resolver(config.brain_for(spec.ministry))
        except Exception as exc:  # noqa: BLE001 — unreadable spec/unknown brain fails the task
            queue.claim(task_id)
            queue.fail(task_id, f"{type(exc).__name__}: {exc}")
            results["failed"].append(task_id)
            continue

        running = queue.claim(task_id)
        try:
            runner.run(running)
        except Exception as exc:  # noqa: BLE001 — any brain failure fails only this task
            queue.fail(task_id, f"{type(exc).__name__}: {exc}")
            results["failed"].append(task_id)
        else:
            queue.complete(task_id)
            results["done"].append(task_id)
    return results
