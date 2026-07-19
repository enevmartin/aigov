"""All task types: schemas, per-type artifact requirements, publish gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.config import AppConfig
from core.contracts import (
    OPTIONAL_ARTIFACTS,
    REPORT_MODEL,
    REQUIRED_ARTIFACTS,
    CrisisReport,
    JointReport,
    SignalStats,
    SystemHealth,
    TaskSpec,
    TaskType,
)
from core.publish import publish_all
from core.queue import FileQueue, QueueState
from tests.fake_brain import FakeBrain

CITATION = {
    "url": "https://www.bnb.bg/Statistics/",
    "title": "БНБ — статистика",
    "retrieved": "2026-07-20",
}

REPORT_BASE = {
    "ministry": "finance",
    "date": "2026-07-20",
    "title": "Тест",
    "summary": "Тест.",
    "sources": [CITATION],
}


class TestSchemas:
    def test_crisis_report_requires_confidence_and_keywords(self) -> None:
        report = CrisisReport.model_validate(
            {**REPORT_BASE, "confidence": "high", "trigger_keywords": ["дефицит"]}
        )
        assert report.confidence == "high"
        with pytest.raises(ValidationError):
            CrisisReport.model_validate(REPORT_BASE)  # no confidence

    def test_joint_report_requires_two_contributors(self) -> None:
        JointReport.model_validate({**REPORT_BASE, "contributors": ["finance", "health"]})
        with pytest.raises(ValidationError):
            JointReport.model_validate({**REPORT_BASE, "contributors": ["finance"]})

    def test_signal_stats_total_must_match_buckets(self) -> None:
        SignalStats.model_validate(
            {
                "ministry": "finance",
                "date": "2026-07-20",
                "total": 3,
                "categories": [
                    {"category": "инфраструктура", "count": 2},
                    {"category": "друго", "count": 1},
                ],
            }
        )
        with pytest.raises(ValidationError, match="total"):
            SignalStats.model_validate(
                {
                    "ministry": "finance",
                    "date": "2026-07-20",
                    "total": 99,
                    "categories": [{"category": "друго", "count": 1}],
                }
            )

    def test_system_health_shape(self) -> None:
        health = SystemHealth.model_validate(
            {
                "generated": "2026-07-20T06:00:00Z",
                "sources": [
                    {
                        "ministry": "finance",
                        "name": "Economic.bg",
                        "url": "https://www.economic.bg/rss/ikonomika.xml",
                        "status": "degraded",
                        "consecutive_failures": 3,
                    }
                ],
                "events": [
                    {
                        "timestamp": "2026-07-20T06:00:00Z",
                        "kind": "data_quality_alert",
                        "ministry": "finance",
                        "message": "източникът е недостъпен 3 поредни пъти",
                    }
                ],
            }
        )
        assert health.sources[0].status == "degraded"

    def test_every_task_type_has_artifact_requirements(self) -> None:
        for task_type in TaskType:
            assert task_type in REQUIRED_ARTIFACTS
            assert task_type in OPTIONAL_ARTIFACTS
            assert task_type in REPORT_MODEL
            assert REQUIRED_ARTIFACTS[task_type], "every type must publish something"


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig.model_validate(
        {"brain": "claude_code", "ministries": ["finance", "government"]}
    )
    cfg.root = tmp_path
    return cfg


def run_type(config: AppConfig, task_type: str, ministry: str = "finance") -> FileQueue:
    queue = FileQueue(config.path("tasks"))
    task_id = f"{ministry}-2026-07-20-{task_type.replace('_', '-')}"
    spec = TaskSpec.model_validate(
        {"id": task_id, "ministry": ministry, "type": task_type, "created": "2026-07-20T06:00:00"}
    )
    input_files = {"staging/data.parquet": b"x"}
    if task_type == "joint_report":
        input_files = {
            "published/finance/2026-07-19/report.md": b"a",
            "published/health/2026-07-19/report.md": b"b",
        }
    queue.enqueue(spec, input_files=input_files)
    queue.claim(task_id)
    FakeBrain().run(queue.path(QueueState.RUNNING, task_id))
    queue.complete(task_id)
    return queue


class TestPublishPerType:
    @pytest.mark.parametrize(
        ("task_type", "expected_files"),
        [
            ("analysis", {"report.md", "aggregates.json"}),
            ("news_digest", {"report.md", "aggregates.json", "news.json"}),
            ("weekly_report", {"report.md", "aggregates.json"}),
            ("crisis_brief", {"report.md"}),
            ("signal_triage", {"signals.json"}),
        ],
    )
    def test_fake_brain_output_publishes(
        self, config: AppConfig, task_type: str, expected_files: set[str]
    ) -> None:
        run_type(config, task_type)
        results = publish_all(config)
        assert len(results["published"]) == 1, results
        day_dir = config.path("published") / "finance" / "2026-07-20"
        assert {p.name for p in day_dir.iterdir()} == expected_files

    def test_joint_report_publishes_under_government(self, config: AppConfig) -> None:
        run_type(config, "joint_report", ministry="government")
        results = publish_all(config)
        assert len(results["published"]) == 1
        report = (
            config.path("published") / "government" / "2026-07-20" / "report.md"
        ).read_text(encoding="utf-8")
        assert "contributors:" in report

    def test_crisis_without_confidence_rejected(self, config: AppConfig) -> None:
        queue = run_type(config, "crisis_brief")
        done = queue.path(QueueState.DONE, "finance-2026-07-20-crisis-brief")
        report = (done / "output" / "report.md").read_text(encoding="utf-8")
        (done / "output" / "report.md").write_text(
            report.replace("confidence: medium\n", ""), encoding="utf-8"
        )
        results = publish_all(config)
        assert results["rejected"] == ["finance-2026-07-20-crisis-brief"]

    def test_signal_triage_never_publishes_raw_material(self, config: AppConfig) -> None:
        """Only signals.json (+ optional report) can go public — never input."""
        run_type(config, "signal_triage")
        publish_all(config)
        day_dir = config.path("published") / "finance" / "2026-07-20"
        published = {p.name for p in day_dir.iterdir()}
        assert "signals.json" in published
        assert not any("staging" in name or "parquet" in name for name in published)
        stats = json.loads((day_dir / "signals.json").read_text(encoding="utf-8"))
        assert stats["total"] == sum(c["count"] for c in stats["categories"])
