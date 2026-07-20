"""Corrections: full cycle, sidecar linkage, inviolable history."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from core.cli import main
from core.config import AppConfig
from core.contracts import CorrectionReport, TaskSpec
from core.publish import publish_all
from core.queue import FileQueue, QueueState
from core.session import run_session
from tests.fake_brain import FakeBrain, approve_marker


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {"brain": "claude_code", "ministries": ["finance"], "brains": {}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (tmp_path / "ministries" / "finance" / "prompts").mkdir(parents=True)
    return tmp_path


def publish_original(repo: Path, task_id: str = "finance-2026-07-19-an") -> AppConfig:
    config = AppConfig.model_validate({"brain": "claude_code", "ministries": ["finance"]})
    config.root = repo
    queue = FileQueue(config.path("tasks"))
    queue.enqueue(
        TaskSpec.model_validate(
            {
                "id": task_id,
                "ministry": "finance",
                "type": "analysis",
                "created": "2026-07-19T06:00:00",
            }
        ),
        input_files={"staging/x.parquet": b"x"},
    )
    queue.claim(task_id)
    FakeBrain().run(queue.path(QueueState.RUNNING, task_id))
    approve_marker(queue.complete(task_id))
    assert publish_all(config)["published"] == [task_id]
    return config


class TestCorrectionCycle:
    def test_full_cycle_with_sidecar_and_immutable_original(self, repo: Path) -> None:
        config = publish_original(repo)
        original_dir = config.path("published") / "finance" / "2026-07-19" / "analysis"
        before = {
            p.name: p.read_bytes() for p in original_dir.iterdir() if p.is_file()
        }

        # operator orders the correction
        assert main(["--root", str(repo), "correct", "finance", "2026-07-19",
                     "--note", "грешно число за инфлацията"]) == 0
        queue = FileQueue(config.path("tasks"))
        [task_id] = queue.list_tasks(QueueState.PENDING)
        assert task_id.endswith("-correction")
        task_input = queue.path(QueueState.PENDING, task_id) / "input"
        assert (task_input / "original" / "report.md").is_file()
        request = json.loads(
            (task_input / "correction_request.json").read_text(encoding="utf-8")
        )
        assert "инфлацията" in request["note"]

        # correction runs through session (incl. review) and publishes
        results = run_session(config, lambda _n: FakeBrain())
        assert results["done"] == [task_id]
        publish = publish_all(config)
        assert publish["published"] == [task_id]

        # the correction is its own publication carrying corrects:
        correction_days = sorted(
            p.name for p in (config.path("published") / "finance").iterdir() if p.is_dir()
        )
        correction_day = [d for d in correction_days if d != "2026-07-19"][0]
        correction_report = (
            config.path("published") / "finance" / correction_day / "correction" / "report.md"
        ).read_text(encoding="utf-8")
        assert "corrects:" in correction_report
        assert "2026-07-19" in correction_report

        # the original gained the sidecar...
        sidecar = json.loads(
            (original_dir / "corrected_by.json").read_text(encoding="utf-8")
        )
        [link] = sidecar["corrections"]
        assert link["date"] == correction_day

        # ...and its own artifacts are byte-identical (history inviolable)
        after = {
            p.name: p.read_bytes()
            for p in original_dir.iterdir()
            if p.is_file() and p.name != "corrected_by.json"
        }
        assert after == before

    def test_correction_for_unknown_publication_rejected(self, repo: Path) -> None:
        config = publish_original(repo)
        assert (
            main(["--root", str(repo), "correct", "finance", "2020-01-01"]) == 1
        )  # CLI refuses: nothing there

        # a brain fabricating a bad reference is caught by the publish gate
        queue = FileQueue(config.path("tasks"))
        queue.enqueue(
            TaskSpec.model_validate(
                {
                    "id": "finance-2026-07-20-correction",
                    "ministry": "finance",
                    "type": "correction",
                    "created": "2026-07-20T06:00:00",
                }
            ),
            input_files={
                "correction_request.json": json.dumps(
                    {"ministry": "finance", "date": "2020-01-01"}
                ).encode("utf-8")
            },
        )
        queue.claim("finance-2026-07-20-correction")
        FakeBrain().run(queue.path(QueueState.RUNNING, "finance-2026-07-20-correction"))
        approve_marker(queue.complete("finance-2026-07-20-correction"))
        results = publish_all(config)
        assert results["rejected"] == ["finance-2026-07-20-correction"]
        reason = (
            queue.path(QueueState.FAILED, "finance-2026-07-20-correction") / "reason.txt"
        ).read_text(encoding="utf-8")
        assert "unknown publication" in reason


class TestCorrectionSchema:
    def test_correction_requires_corrects_ref(self) -> None:
        from pydantic import ValidationError

        base = {
            "ministry": "finance",
            "date": "2026-07-20",
            "title": "Поправка",
            "summary": "…",
            "sources": [
                {"url": "https://bnb.bg/", "title": "БНБ", "retrieved": "2026-07-20"}
            ],
        }
        with pytest.raises(ValidationError):
            CorrectionReport.model_validate(base)
        report = CorrectionReport.model_validate(
            {**base, "corrects": {"ministry": "finance", "date": "2026-07-19"}}
        )
        assert report.corrects.date.isoformat() == "2026-07-19"
