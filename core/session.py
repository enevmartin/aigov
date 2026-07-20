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

import json
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Protocol

from core.config import AppConfig
from core.publish.health import record_event, record_session_details
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
    (older than :data:`STALE_AFTER`).

    Second reading (чл. фаза-3): when an ORIGINAL task completes, the core
    parks it in ``review/`` and enqueues its review task, which this same
    session then processes (the drain loop picks up newly enqueued work).
    A completed review task is consumed immediately: approve returns the
    original to ``done/`` (publishable), revise sends it back to
    ``pending/`` for the NEXT session (bounded by the revision limit).

    Returns ``{"done": [...], "failed": [...], "retried": [...], "resumed":
    [...], "approved": [...], "revised": [...]}``.
    """
    queue = FileQueue(config.path("tasks"))
    resumed = queue.requeue_stale(STALE_AFTER)
    results: dict[str, list[str]] = {
        "done": [],
        "failed": [],
        "retried": [],
        "resumed": resumed,
        "approved": [],
        "revised": [],
    }

    processed: set[str] = set()
    records: list[dict[str, object]] = []
    while True:
        pending = [t for t in queue.list_tasks(QueueState.PENDING) if t not in processed]
        if not pending:
            break
        for task_id in pending:
            processed.add(task_id)
            _run_one(config, queue, resolver, task_id, results, records)

    record_session_details(config, records)
    return results


def _read_usage(task_dir: Path) -> dict[str, object] | None:
    """Token usage a brain may have reported (``usage.json`` in the task dir)."""
    marker = task_dir / "usage.json"
    if not marker.is_file():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return dict(payload) if isinstance(payload, dict) else None


def _run_one(
    config: AppConfig,
    queue: FileQueue,
    resolver: BrainResolver,
    task_id: str,
    results: dict[str, list[str]],
    records: list[dict[str, object]],
) -> None:
    """Claim, run and post-process a single task (incl. review bookkeeping)."""
    from core import review as review_flow  # local import: keep module deps one-way

    ministry: str | None = None
    task_type: str | None = None
    brain_name: str | None = None
    started = time.monotonic()
    usage: dict[str, object] | None = None

    def record(outcome: str) -> None:
        records.append(
            {
                "id": task_id,
                "ministry": ministry,
                "type": task_type,
                "brain": brain_name,
                "duration_s": round(time.monotonic() - started, 3),
                "tokens": usage,
                "outcome": outcome,
            }
        )

    try:
        spec = queue.load_spec(QueueState.PENDING, task_id)
        ministry = spec.ministry
        task_type = spec.type.value
        brain_name = config.brain_for(spec.ministry)
        runner = resolver(brain_name)
    except Exception as exc:  # noqa: BLE001 — unreadable spec/unknown brain
        queue.claim(task_id)
        _handle_failure(
            config, queue, task_id, ministry, f"{type(exc).__name__}: {exc}", results
        )
        record("failed")
        return

    running = queue.claim(task_id)
    try:
        runner.run(running)
    except Exception as exc:  # noqa: BLE001 — any brain failure fails only this task
        usage = _read_usage(running) if running.is_dir() else None
        _handle_failure(
            config, queue, task_id, ministry, f"{type(exc).__name__}: {exc}", results
        )
        record("failed" if task_id in results["failed"] else "retried")
        return

    usage = _read_usage(running)
    queue.complete(task_id)
    if spec.type.value == "review":
        try:
            outcome = review_flow.apply_verdict(config, queue, task_id)
        except Exception as exc:  # noqa: BLE001 — a broken review must not stop the session
            queue.fail(task_id, f"invalid review output: {type(exc).__name__}: {exc}")
            results["failed"].append(task_id)
            record("failed")
            return
        original = review_flow.original_task_id(task_id)
        if outcome == "approved":
            results["approved"].append(original)
        elif outcome == "revised":
            results["revised"].append(original)
        else:
            results["failed"].append(original)
        record(outcome)
    else:
        results["done"].append(task_id)
        review_flow.create_review_task(queue, task_id)
        record("done")
