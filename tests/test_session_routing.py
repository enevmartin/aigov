"""Per-task brain routing: two ministries, two brains, one session."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import AppConfig
from core.contracts import TaskSpec
from core.queue import FileQueue, QueueState
from core.session import run_session
from tests.fake_brain import FakeBrain


class RecordingFakeBrain(FakeBrain):
    """Fake brain that records which task directories it processed."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.seen: list[str] = []

    def run(self, task_dir: Path) -> object:
        self.seen.append(task_dir.name)
        return super().run(task_dir)


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig.model_validate(
        {
            "brain": "fake_a",  # global default
            "ministries": [
                {"slug": "finance"},                      # -> global fake_a
                {"slug": "health", "brain": "fake_b"},    # -> override fake_b
            ],
        }
    )
    cfg.root = tmp_path
    return cfg


def enqueue(config: AppConfig, task_id: str, ministry: str) -> FileQueue:
    queue = FileQueue(config.path("tasks"))
    queue.enqueue(
        TaskSpec.model_validate(
            {
                "id": task_id,
                "ministry": ministry,
                "type": "news_digest",
                "created": "2026-07-20T06:00:00",
            }
        )
    )
    return queue


def test_each_ministry_processed_by_its_own_brain(config: AppConfig) -> None:
    queue = enqueue(config, "finance-2026-07-20-digest", "finance")
    enqueue(config, "health-2026-07-20-digest", "health")

    brains = {"fake_a": RecordingFakeBrain("a"), "fake_b": RecordingFakeBrain("b")}
    results = run_session(config, lambda name: brains[name])

    assert sorted(results["done"]) == [
        "finance-2026-07-20-digest",
        "health-2026-07-20-digest",
    ]
    # each brain saw its own ministry's task AND its review (same brain reviews)
    assert brains["fake_a"].seen == [
        "finance-2026-07-20-digest",
        "finance-2026-07-20-digest-review",
    ]
    assert brains["fake_b"].seen == [
        "health-2026-07-20-digest",
        "health-2026-07-20-digest-review",
    ]
    assert len(queue.list_tasks(QueueState.DONE)) == 2


def test_unknown_ministry_falls_back_to_global_brain(config: AppConfig) -> None:
    """A task for a ministry missing from config still runs (global brain)."""
    enqueue(config, "mystery-2026-07-20-digest", "mystery")
    brains = {"fake_a": RecordingFakeBrain("a"), "fake_b": RecordingFakeBrain("b")}
    results = run_session(config, lambda name: brains[name])
    assert results["done"] == ["mystery-2026-07-20-digest"]
    assert brains["fake_a"].seen == [
        "mystery-2026-07-20-digest",
        "mystery-2026-07-20-digest-review",
    ]


def test_unresolvable_brain_fails_only_that_task(config: AppConfig) -> None:
    queue = enqueue(config, "finance-2026-07-20-digest", "finance")
    enqueue(config, "health-2026-07-20-digest", "health")

    def resolver(name: str) -> FakeBrain:
        if name == "fake_b":
            raise ImportError("no module named brains.fake_b")
        return FakeBrain()

    # session 1: finance done; health retried (retry policy gives one more shot)
    results = run_session(config, resolver)
    assert results["done"] == ["finance-2026-07-20-digest"]
    assert results["retried"] == ["health-2026-07-20-digest"]

    # session 2: still unresolvable -> failed with the reason
    results = run_session(config, resolver)
    assert results["failed"] == ["health-2026-07-20-digest"]
    reason = (
        queue.path(QueueState.FAILED, "health-2026-07-20-digest") / "reason.txt"
    ).read_text(encoding="utf-8")
    assert "ImportError" in reason
