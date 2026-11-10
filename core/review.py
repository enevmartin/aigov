"""Second reading: no report is published unreviewed.

The review itself is an ORDINARY task through the same brain adapter — the
core adds zero LLM logic. What lives here is deterministic bookkeeping:

- BEFORE any LLM reading, :func:`pre_review` reconciles the report with the
  collectors deterministically (чл. 8): every ``{{ind:<id>}}`` must exist in
  ``input/indicators.json``, no bare numbers, no tier-3 evidence. A failure
  is a ``revise`` decided by the core — no tokens spent on a doomed reading;
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

import frontmatter

from core.config import AppConfig
from core.contracts import (
    EvidenceError,
    ReviewResult,
    ReviewVerdict,
    TaskSpec,
    TaskType,
    TierRegistry,
    validate_evidence,
)
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


CORE_RECONCILER = "core:сверка-с-колекторите"


def reconcile(task_dir: Path, tiers: TierRegistry) -> list[str]:
    """Deterministic number/evidence check of a finished task (no LLM).

    Returns human-readable problems; empty means the numbers and sources of
    ``output/report.md`` match the collectors' ``input/indicators.json``.
    """
    report = task_dir / "output" / "report.md"
    if not report.is_file():
        return []  # signal stats, reviews: no prose numbers to reconcile
    try:
        post = frontmatter.loads(report.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — unparsable output is itself the finding
        return [f"report.md не може да се прочете: {exc}"]
    indicators_path = task_dir / "input" / "indicators.json"
    indicators = (
        {str(i["id"]): i for i in json.loads(indicators_path.read_text(encoding="utf-8"))}
        if indicators_path.is_file()
        else {}
    )
    document = task_dir / "input" / "document.json"
    document_url = (
        str(json.loads(document.read_text(encoding="utf-8"))["url"])
        if document.is_file()
        else None
    )
    try:
        validate_evidence(
            post.metadata, post.content, indicators, tiers.including(indicators, document_url)
        )
    except EvidenceError as exc:
        return [f"чл. 8: {exc}"]
    return []


def pre_review(config: AppConfig, queue: FileQueue, original_id: str) -> str | None:
    """Reconcile before the LLM review; on problems send the task back.

    Returns ``None`` when the task may proceed to the (LLM) second reading,
    else the outcome of the core's own ``revise`` (``"revised"``/``"failed"``).
    """
    problems = reconcile(queue.path(QueueState.DONE, original_id), TierRegistry.load(config.root))
    if not problems:
        return None
    spec = queue.load_spec(QueueState.DONE, original_id)
    queue.move(original_id, QueueState.DONE, QueueState.REVIEW)
    return _send_back(config, queue, original_id, spec, problems, CORE_RECONCILER)


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
        outcome = _send_back(config, queue, original_id, spec, result.notes, reviewer)

    shutil.rmtree(review_dir)
    return outcome


def _send_back(
    config: AppConfig,
    queue: FileQueue,
    original_id: str,
    spec: TaskSpec,
    notes: list[str],
    reviewer: str,
) -> str:
    """Revise an original parked in ``review/``: back to pending (once), else fail."""
    original_dir = queue.path(QueueState.REVIEW, original_id)
    revisions_marker = original_dir / REVISIONS_FILE
    revisions = (
        int(revisions_marker.read_text(encoding="utf-8")) if revisions_marker.is_file() else 0
    )
    if revisions >= MAX_REVISIONS:
        queue.fail(
            original_id,
            f"second revise verdict ({reviewer}): " + "; ".join(notes),
            source_state=QueueState.REVIEW,
        )
        record_event(
            config,
            kind="task_failed",
            ministry=spec.ministry,
            message=(
                f"задача {original_id} отхвърлена от второто четене два пъти: "
                + "; ".join(notes)
            ),
        )
        return "failed"
    revisions_marker.write_text(str(revisions + 1), encoding="utf-8")
    notes_payload = {"reviewer": reviewer, "notes": notes, "revision": revisions + 1}
    (original_dir / "input" / f"review_notes-{revisions + 1}.json").write_text(
        json.dumps(notes_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # discard the rejected output so the rerun starts clean
    for stale in (original_dir / "output").glob("*"):
        if stale.is_file():
            stale.unlink()
    queue.move(original_id, QueueState.REVIEW, QueueState.PENDING)
    return "revised"


def is_approved(task_dir: Path) -> bool:
    """Whether an original task carries an approve marker (publish gate)."""
    marker = task_dir / APPROVAL_MARKER
    if not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return bool(payload.get("verdict") == "approve")


def approval_info(task_dir: Path) -> dict[str, object]:
    """The approval marker payload (empty dict when absent)."""
    marker = task_dir / APPROVAL_MARKER
    if not marker.is_file():
        return {}
    return dict(json.loads(marker.read_text(encoding="utf-8")))
