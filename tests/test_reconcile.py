"""Review stage, part 1 — the CORE reconciles every number with the
collectors before any LLM reading (чл. 8). No tokens on a doomed report."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from core.config import AppConfig
from core.contracts import TaskSpec, TierRegistry
from core.queue import FileQueue, QueueState
from core.review import CORE_RECONCILER, reconcile, review_task_id
from core.session import run_session
from tests.fake_brain import FakeBrain
from tests.support import INDICATOR_ID, with_indicators


class TamperingBrain(FakeBrain):
    """Writes a valid report, then swaps a reference for a number / bad ref."""

    def __init__(self, old: str, new: str) -> None:
        self.old, self.new = old, new

    def run(self, task_dir: Path):  # type: ignore[no-untyped-def]
        artifacts = super().run(task_dir)
        report = task_dir / "output" / "report.md"
        text = report.read_text(encoding="utf-8")
        assert self.old in text
        report.write_text(text.replace(self.old, self.new, 1), encoding="utf-8")
        return artifacts


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig.model_validate({"brain": "claude_code", "ministries": ["finance"]})
    cfg.root = tmp_path
    return cfg


def _enqueue(config: AppConfig) -> FileQueue:
    queue = FileQueue(config.path("tasks"))
    spec = TaskSpec(id="finance-2026-11-08-a", ministry="finance", type="analysis",
                    created=datetime(2026, 11, 8, 6))
    queue.enqueue(spec, input_files=with_indicators())
    return queue


@pytest.mark.parametrize(
    ("new", "expected"),
    [
        ("6,4%", "без референция"),                      # model typed a number
        ("{{ind:finance.gov_debt}}", "извън входа"),     # ref to data it was not given
    ],
)
def test_mismatch_is_sent_back_by_the_core_without_llm_review(
    config: AppConfig, new: str, expected: str
) -> None:
    queue = _enqueue(config)
    brain = TamperingBrain(f"{{{{ind:{INDICATOR_ID}}}}}", new)
    results = run_session(config, lambda _n: brain)

    assert results["revised"] == ["finance-2026-11-08-a"]
    assert queue.state_of(review_task_id("finance-2026-11-08-a")) is None  # no LLM review
    notes = json.loads(
        (queue.path(QueueState.PENDING, "finance-2026-11-08-a") / "input"
         / "review_notes-1.json").read_text(encoding="utf-8")
    )
    assert notes["reviewer"] == CORE_RECONCILER
    assert expected in notes["notes"][0]


def test_second_mismatch_fails_the_task(config: AppConfig) -> None:
    queue = _enqueue(config)
    brain = TamperingBrain(f"{{{{ind:{INDICATOR_ID}}}}}", "6,4%")
    run_session(config, lambda _n: brain)           # 1st: revised
    results = run_session(config, lambda _n: brain)  # 2nd: same mistake
    assert results["failed"] == ["finance-2026-11-08-a"]
    assert queue.state_of("finance-2026-11-08-a") == QueueState.FAILED


def test_correct_report_goes_on_to_the_llm_review(config: AppConfig) -> None:
    queue = _enqueue(config)
    results = run_session(config, lambda _n: FakeBrain())
    assert results["approved"] == ["finance-2026-11-08-a"]  # fake reviewer approved
    assert queue.state_of("finance-2026-11-08-a") == QueueState.DONE


def test_reconcile_reports_nothing_for_artifacts_without_prose(tmp_path: Path) -> None:
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "signals.json").write_text("{}", encoding="utf-8")
    assert reconcile(tmp_path, TierRegistry()) == []
