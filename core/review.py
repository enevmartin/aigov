"""Second reading: no report is published unreviewed.

The review itself is an ORDINARY task through the same brain adapter — the
core adds zero LLM logic. What lives here is deterministic bookkeeping:

- when an original task completes, :func:`create_review_task` parks it in
  ``review/`` and enqueues a review task whose input is the original's
  output + original input;
- when the review task completes, :func:`apply_verdict` reads
  ``review.json``: *approve* stamps the original (marker file) and returns
  it to ``done/`` for publishing; *revise* sends it back to ``pending/``
  with the notes added to its input — at most once; a second revise fails
  the task and raises a health event.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from core.config import AppConfig
from core.contracts import ReviewResult, ReviewVerdict, TaskSpec, TaskType
from core.publish.health import record_event
from core.queue import FileQueue, QueueState

REVIEW_SUFFIX = "-review"
APPROVAL_MARKER = "review.json"  # in the ORIGINAL task dir (not output/)
REVISIONS_FILE = "revisions.txt"
MAX_REVISIONS = 1


def review_task_id(original_id: str) -> str:
    """The id of the review task for *original_id*."""
    return f"{original_id}{REVIEW_SUFFIX}"


def original_task_id(review_id: str) -> str:
    """Inverse of :func:`review_task_id`."""
    return review_id.removesuffix(REVIEW_SUFFIX)


def is_review_task(task_id: str) -> bool:
    """Whether *task_id* names a review task."""
    return task_id.endswith(REVIEW_SUFFIX)


def create_review_task(queue: FileQueue, original_id: str) -> str:
    """Park the completed original in ``review/`` and enqueue its review.

    The review task's input carries the original's ``output/`` (what is
    being judged) and the original's ``input/`` (the evidence every claim
    must trace to).
    """
    spec = queue.load_spec(QueueState.DONE, original_id)
    original_dir = queue.move(original_id, QueueState.DONE, QueueState.REVIEW)

    input_files: dict[str, bytes] = {}
    for area, prefix in (("output", "original_output"), ("input", "original_input")):
        base = original_dir / area
        if base.is_dir():
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    key = f"{prefix}/{path.relative_to(base).as_posix()}"
                    input_files[key] = path.read_bytes()

    review_spec = TaskSpec(
        id=review_task_id(original_id),
        ministry=spec.ministry,
        type=TaskType.REVIEW,
        created=datetime.now(tz=UTC),
    )
    queue.enqueue(review_spec, input_files=input_files)
    return review_spec.id


def apply_verdict(config: AppConfig, queue: FileQueue, review_id: str) -> str:
    """Consume a completed review task; move the original accordingly.

    Returns ``"approved"``, ``"revised"`` or ``"failed"``. The review task
    directory is deleted afterwards — its verdict lives on as the approval
    marker (or the revision notes) on the original.
    """
    review_dir = queue.path(QueueState.DONE, review_id)
    result = ReviewResult.model_validate(
        json.loads((review_dir / "output" / "review.json").read_text(encoding="utf-8"))
    )
    original_id = original_task_id(review_id)
    original_dir = queue.path(QueueState.REVIEW, original_id)
    if not original_dir.is_dir():
        raise FileNotFoundError(f"original task {original_id!r} not in review/")

    spec = queue.load_spec(QueueState.REVIEW, original_id)
    reviewer = result.reviewer or config.brain_for(spec.ministry)

    if result.verdict is ReviewVerdict.APPROVE:
        marker = {
            "verdict": "approve",
            "notes": result.notes,
            "reviewer": reviewer,
            "reviewed_at": datetime.now(tz=UTC).isoformat(),
        }
        (original_dir / APPROVAL_MARKER).write_text(
            json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        queue.move(original_id, QueueState.REVIEW, QueueState.DONE)
        outcome = "approved"
    else:
        revisions_marker = original_dir / REVISIONS_FILE
        revisions = (
            int(revisions_marker.read_text(encoding="utf-8"))
            if revisions_marker.is_file()
            else 0
        )
        if revisions >= MAX_REVISIONS:
            queue.fail(original_id, "second revise verdict from review", source_state=QueueState.REVIEW)
            record_event(
                config,
                kind="task_failed",
                ministry=spec.ministry,
                message=(
                    f"задача {original_id} отхвърлена от второто четене два пъти: "
                    + "; ".join(result.notes)
                ),
            )
            outcome = "failed"
        else:
            revisions_marker.write_text(str(revisions + 1), encoding="utf-8")
            notes_payload = {
                "reviewer": reviewer,
                "notes": result.notes,
                "revision": revisions + 1,
            }
            (original_dir / "input" / f"review_notes-{revisions + 1}.json").write_text(
                json.dumps(notes_payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            # discard the rejected output so the rerun starts clean
            for stale in (original_dir / "output").glob("*"):
                if stale.is_file():
                    stale.unlink()
            queue.move(original_id, QueueState.REVIEW, QueueState.PENDING)
            outcome = "revised"

    shutil.rmtree(review_dir)
    return outcome


def is_approved(task_dir: Path) -> bool:
    """Whether an original task carries an approve marker (publish gate)."""
    marker = task_dir / APPROVAL_MARKER
    if not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return payload.get("verdict") == "approve"


def approval_info(task_dir: Path) -> dict[str, object]:
    """The approval marker payload (empty dict when absent)."""
    marker = task_dir / APPROVAL_MARKER
    if not marker.is_file():
        return {}
    return dict(json.loads(marker.read_text(encoding="utf-8")))
