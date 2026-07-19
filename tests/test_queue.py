"""File queue tests: atomic transitions, race safety, crash recovery."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.contracts import TaskSpec
from core.queue import FileQueue, QueueState


@pytest.fixture
def queue(tmp_path: Path) -> FileQueue:
    return FileQueue(tmp_path / "tasks")


def make_spec(task_id: str = "finance-2026-07-19-news") -> TaskSpec:
    return TaskSpec.model_validate(
        {
            "id": task_id,
            "ministry": "finance",
            "type": "news_digest",
            "created": "2026-07-19T06:00:00",
        }
    )


class TestEnqueue:
    def test_creates_pending_directory_with_contract_files(self, queue: FileQueue) -> None:
        path = queue.enqueue(
            make_spec(),
            input_files={"news/feed.json": b"[]"},
            expected_schema='{"type": "object"}',
        )
        assert path == queue.path(QueueState.PENDING, "finance-2026-07-19-news")
        assert (path / "task.yaml").is_file()
        assert (path / "input" / "news" / "feed.json").read_bytes() == b"[]"
        assert (path / "expected.schema.json").is_file()

    def test_task_yaml_round_trips_through_contract(self, queue: FileQueue) -> None:
        queue.enqueue(make_spec())
        spec = queue.load_spec(QueueState.PENDING, "finance-2026-07-19-news")
        assert spec.ministry == "finance"
        assert spec.created == datetime(2026, 7, 19, 6, 0)

    def test_duplicate_id_rejected_in_any_state(self, queue: FileQueue) -> None:
        queue.enqueue(make_spec())
        with pytest.raises(FileExistsError, match="pending"):
            queue.enqueue(make_spec())
        queue.claim("finance-2026-07-19-news")
        with pytest.raises(FileExistsError, match="running"):
            queue.enqueue(make_spec())

    def test_no_staging_leftovers_visible(self, queue: FileQueue) -> None:
        queue.enqueue(make_spec())
        assert queue.list_tasks(QueueState.PENDING) == ["finance-2026-07-19-news"]


class TestTransitions:
    def test_claim_complete_flow(self, queue: FileQueue) -> None:
        queue.enqueue(make_spec())
        running = queue.claim("finance-2026-07-19-news")
        assert running.parent.name == "running"
        assert queue.list_tasks(QueueState.PENDING) == []

        done = queue.complete("finance-2026-07-19-news")
        assert done.parent.name == "done"
        assert queue.state_of("finance-2026-07-19-news") == QueueState.DONE

    def test_claim_race_only_one_winner(self, queue: FileQueue) -> None:
        """Second claim of the same task must fail, not duplicate it."""
        queue.enqueue(make_spec())
        queue.claim("finance-2026-07-19-news")
        with pytest.raises(FileNotFoundError):
            queue.claim("finance-2026-07-19-news")

    def test_fail_records_reason(self, queue: FileQueue) -> None:
        queue.enqueue(make_spec())
        queue.claim("finance-2026-07-19-news")
        failed = queue.fail("finance-2026-07-19-news", "aggregates.json invalid: labels mismatch")
        assert failed.parent.name == "failed"
        assert "labels mismatch" in (failed / "reason.txt").read_text(encoding="utf-8")

    def test_fail_from_done_state(self, queue: FileQueue) -> None:
        """Publish rejects a done task -> failed (used by core/publish)."""
        queue.enqueue(make_spec())
        queue.claim("finance-2026-07-19-news")
        queue.complete("finance-2026-07-19-news")
        failed = queue.fail(
            "finance-2026-07-19-news", "no report.md", source_state=QueueState.DONE
        )
        assert failed.parent.name == "failed"

    def test_unknown_state_rejected(self, queue: FileQueue) -> None:
        with pytest.raises(ValueError, match="unknown queue state"):
            queue.path("archived", "x")
        with pytest.raises(ValueError, match="unknown queue state"):
            queue.list_tasks("archived")


class TestRecovery:
    def test_requeue_stale_returns_crashed_tasks(self, queue: FileQueue) -> None:
        queue.enqueue(make_spec())
        running = queue.claim("finance-2026-07-19-news")

        # Simulate a crash long ago: age the task.yaml mtime by 3 hours.
        marker = running / "task.yaml"
        old = (datetime.now(tz=UTC) - timedelta(hours=3)).timestamp()
        os.utime(marker, (old, old))

        requeued = queue.requeue_stale(older_than=timedelta(hours=1))
        assert requeued == ["finance-2026-07-19-news"]
        assert queue.state_of("finance-2026-07-19-news") == QueueState.PENDING

    def test_fresh_running_tasks_untouched(self, queue: FileQueue) -> None:
        queue.enqueue(make_spec())
        queue.claim("finance-2026-07-19-news")
        assert queue.requeue_stale(older_than=timedelta(hours=1)) == []
        assert queue.state_of("finance-2026-07-19-news") == QueueState.RUNNING
