"""Second reading: approve, revise->fix->approve, revise->revise->failed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config import AppConfig
from core.contracts import ReviewResult, TaskSpec
from core.publish import publish_all
from core.queue import FileQueue, QueueState
from core.session import run_session
from tests.fake_brain import FakeBrain


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig.model_validate({"brain": "fake", "ministries": ["finance"]})
    cfg.root = tmp_path
    return cfg


def enqueue(config: AppConfig, task_id: str = "finance-2026-07-20-digest") -> FileQueue:
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


class ReviewingBrain(FakeBrain):
    """Fake brain whose review verdicts follow a script."""

    def __init__(self, verdicts: list[str]) -> None:
        self.verdicts = verdicts
        self.reviews_done = 0
        self.original_runs = 0
        self.saw_notes_on_rerun = False

    def run(self, task_dir: Path) -> object:
        if task_dir.name.endswith("-review"):
            verdict = self.verdicts[self.reviews_done]
            self.reviews_done += 1
            output = task_dir / "output"
            output.mkdir(exist_ok=True)
            payload = {
                "verdict": verdict,
                "notes": ["числото за инфлация не съвпада с aggregates"]
                if verdict == "revise"
                else [],
                "reviewer": "test-reviewer",
            }
            (output / "review.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            from brains.base import ArtifactSet

            return ArtifactSet.from_output_dir(output)
        self.original_runs += 1
        if list((task_dir / "input").glob("review_notes-*.json")):
            self.saw_notes_on_rerun = True
        return super().run(task_dir)


class TestApprovePath:
    def test_task_flows_to_published_with_review_stamp(self, config: AppConfig) -> None:
        queue = enqueue(config)
        brain = ReviewingBrain(verdicts=["approve"])

        results = run_session(config, lambda _n: brain)
        assert results["done"] == ["finance-2026-07-20-digest"]
        assert results["approved"] == ["finance-2026-07-20-digest"]
        assert brain.reviews_done == 1  # review ran in the SAME session
        assert queue.state_of("finance-2026-07-20-digest") == QueueState.DONE
        assert queue.state_of("finance-2026-07-20-digest-review") is None  # consumed

        publish = publish_all(config)
        assert publish["published"] == ["finance-2026-07-20-digest"]
        report = (
            config.path("published") / "finance" / "2026-07-20" / "news_digest" / "report.md"
        ).read_text(encoding="utf-8")
        assert "reviewed: true" in report
        assert "reviewer: test-reviewer" in report

    def test_unreviewed_done_task_is_not_published(self, config: AppConfig) -> None:
        """A task parked in done/ without approval never goes public."""
        queue = enqueue(config)
        queue.claim("finance-2026-07-20-digest")
        FakeBrain().run(queue.path(QueueState.RUNNING, "finance-2026-07-20-digest"))
        queue.complete("finance-2026-07-20-digest")  # no review happened

        results = publish_all(config)
        assert results["published"] == []
        assert results["unreviewed"] == ["finance-2026-07-20-digest"]
        assert queue.state_of("finance-2026-07-20-digest") == QueueState.DONE


class TestRevisePath:
    def test_revise_then_fix_then_approve(self, config: AppConfig) -> None:
        queue = enqueue(config)
        brain = ReviewingBrain(verdicts=["revise", "approve"])

        # session 1: original runs, review says revise -> back to pending
        results = run_session(config, lambda _n: brain)
        assert results["revised"] == ["finance-2026-07-20-digest"]
        assert queue.state_of("finance-2026-07-20-digest") == QueueState.PENDING
        notes = list(
            (queue.path(QueueState.PENDING, "finance-2026-07-20-digest") / "input").glob(
                "review_notes-*.json"
            )
        )
        assert len(notes) == 1
        payload = json.loads(notes[0].read_text(encoding="utf-8"))
        assert "инфлация" in payload["notes"][0]

        # session 2: rerun WITH the notes, second review approves
        results = run_session(config, lambda _n: brain)
        assert brain.saw_notes_on_rerun
        assert results["approved"] == ["finance-2026-07-20-digest"]
        assert publish_all(config)["published"] == ["finance-2026-07-20-digest"]

    def test_second_revise_fails_with_health_event(self, config: AppConfig) -> None:
        queue = enqueue(config)
        brain = ReviewingBrain(verdicts=["revise", "revise"])

        run_session(config, lambda _n: brain)  # revise #1
        results = run_session(config, lambda _n: brain)  # revise #2 -> failed
        assert results["failed"] == ["finance-2026-07-20-digest"]
        assert queue.state_of("finance-2026-07-20-digest") == QueueState.FAILED
        reason = (
            queue.path(QueueState.FAILED, "finance-2026-07-20-digest") / "reason.txt"
        ).read_text(encoding="utf-8")
        assert "second revise" in reason

        health = json.loads(
            (config.path("published") / "system" / "health.json").read_text(encoding="utf-8")
        )
        assert any(
            e["kind"] == "task_failed" and "второто четене" in e["message"]
            for e in health["events"]
        )


class TestReviewContract:
    def test_revise_without_notes_is_invalid(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="concrete notes"):
            ReviewResult.model_validate({"verdict": "revise", "notes": []})
