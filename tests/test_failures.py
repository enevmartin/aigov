"""Failure situations: retry policy, resumable sessions, isolation."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.config import AppConfig
from core.contracts import TaskSpec
from core.publish import publish_all
from core.queue import FileQueue, QueueState
from core.session import ATTEMPTS_FILE, STALE_AFTER, run_session
from tests.fake_brain import FakeBrain


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig.model_validate({"brain": "fake", "ministries": ["finance"]})
    cfg.root = tmp_path
    return cfg


def enqueue(config: AppConfig, task_id: str) -> FileQueue:
    queue = FileQueue(config.path("tasks"))
    queue.enqueue(
        TaskSpec.model_validate(
            {
                "id": task_id,
                "ministry": "finance",
                "type": "news_digest",
                "created": "2026-07-20T06:00:00",
            }
        ),
        input_files={"staging/x.parquet": b"x"},
    )
    return queue


class FlakyBrain(FakeBrain):
    """Fails the first N runs of each task, then behaves like the fake brain."""

    def __init__(self, failures: int) -> None:
        self.failures_left = failures
        self.runs = 0

    def run(self, task_dir: Path) -> object:
        self.runs += 1
        if self.failures_left > 0:
            self.failures_left -= 1
            raise RuntimeError("мозъкът се задави")
        return super().run(task_dir)


class TestRetryPolicy:
    def test_first_failure_retries_second_fails_with_alert(self, config: AppConfig) -> None:
        queue = enqueue(config, "finance-2026-07-20-digest")
        brain = FlakyBrain(failures=2)

        # session 1: failure -> released back to pending with attempt counter
        results = run_session(config, lambda _n: brain)
        assert results["retried"] == ["finance-2026-07-20-digest"]
        assert results["failed"] == []
        assert queue.state_of("finance-2026-07-20-digest") == QueueState.PENDING
        attempts = (
            queue.path(QueueState.PENDING, "finance-2026-07-20-digest") / ATTEMPTS_FILE
        ).read_text(encoding="utf-8")
        assert attempts == "1"

        # session 2: second failure -> failed/ + reason + health alert
        results = run_session(config, lambda _n: brain)
        assert results["failed"] == ["finance-2026-07-20-digest"]
        reason = (
            queue.path(QueueState.FAILED, "finance-2026-07-20-digest") / "reason.txt"
        ).read_text(encoding="utf-8")
        assert "мозъкът се задави" in reason

        health = json.loads(
            (config.path("published") / "system" / "health.json").read_text(encoding="utf-8")
        )
        kinds = [e["kind"] for e in health["events"]]
        assert "task_failed" in kinds

    def test_retried_task_succeeds_next_session(self, config: AppConfig) -> None:
        queue = enqueue(config, "finance-2026-07-20-digest")
        brain = FlakyBrain(failures=1)
        run_session(config, lambda _n: brain)  # fails once -> retry
        results = run_session(config, lambda _n: brain)  # succeeds
        assert results["done"] == ["finance-2026-07-20-digest"]
        assert queue.state_of("finance-2026-07-20-digest") == QueueState.DONE


class TestResumableSessions:
    def test_interrupted_session_resumes_from_unprocessed_task(
        self, config: AppConfig
    ) -> None:
        """Simulated dead session: one task stranded in running/, one pending."""
        queue = enqueue(config, "finance-2026-07-20-a")
        enqueue(config, "finance-2026-07-20-b")

        # the dead session had claimed task A hours ago and never finished
        running = queue.claim("finance-2026-07-20-a")
        old = (datetime.now(tz=UTC) - STALE_AFTER - timedelta(minutes=5)).timestamp()
        os.utime(running / "task.yaml", (old, old))

        results = run_session(config, lambda _n: FakeBrain())
        assert results["resumed"] == ["finance-2026-07-20-a"]
        assert sorted(results["done"]) == ["finance-2026-07-20-a", "finance-2026-07-20-b"]

    def test_freshly_claimed_task_not_stolen(self, config: AppConfig) -> None:
        """A live session's task (claimed now) must not be reclaimed."""
        queue = enqueue(config, "finance-2026-07-20-a")
        queue.claim("finance-2026-07-20-a")  # claim() touches task.yaml
        results = run_session(config, lambda _n: FakeBrain())
        assert results["resumed"] == []
        assert queue.state_of("finance-2026-07-20-a") == QueueState.RUNNING

    def test_claim_measures_staleness_from_claim_not_enqueue(
        self, config: AppConfig
    ) -> None:
        """A task enqueued long ago but claimed just now is NOT stale."""
        queue = enqueue(config, "finance-2026-07-20-a")
        pending_marker = queue.path(QueueState.PENDING, "finance-2026-07-20-a") / "task.yaml"
        old = (datetime.now(tz=UTC) - timedelta(hours=5)).timestamp()
        os.utime(pending_marker, (old, old))

        queue.claim("finance-2026-07-20-a")  # must refresh the clock
        assert queue.requeue_stale(STALE_AFTER) == []


class TestIsolation:
    def test_one_bad_output_never_blocks_other_publications(
        self, config: AppConfig
    ) -> None:
        queue = enqueue(config, "finance-2026-07-20-a")
        enqueue(config, "finance-2026-07-20-b")
        run_session(config, lambda _n: FakeBrain())

        # corrupt ONE done output
        bad = queue.path(QueueState.DONE, "finance-2026-07-20-a") / "output" / "news.json"
        bad.write_text("{счупено", encoding="utf-8")

        results = publish_all(config)
        assert results["published"] == ["finance-2026-07-20-b"]
        assert results["rejected"] == ["finance-2026-07-20-a"]
        report = config.path("published") / "finance" / "2026-07-20" / "news_digest" / "report.md"
        assert report.is_file()
