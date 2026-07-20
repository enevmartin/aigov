"""Institutional memory: archive growth, idempotency, history input."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.archive import history_payload, ingest_aggregates, rebuild_timeseries
from core.config import AppConfig
from core.contracts import Aggregates, TaskSpec
from core.publish import publish_all
from core.queue import FileQueue, QueueState
from tests.fake_brain import FakeBrain, approve_marker

CITATION = {"url": "https://www.bnb.bg/", "title": "БНБ", "retrieved": "2026-07-20"}


def make_aggregates(date: str, labels: list[str], values: list[float]) -> Aggregates:
    return Aggregates.model_validate(
        {
            "ministry": "finance",
            "date": date,
            "series": [
                {
                    "name": "Инфлация (%)",
                    "unit": "%",
                    "labels": labels,
                    "values": values,
                    "source": CITATION,
                }
            ],
        }
    )


class TestStore:
    def test_two_publishes_grow_the_series(self, tmp_path: Path) -> None:
        db = tmp_path / "archive.duckdb"
        ingest_aggregates(db, make_aggregates("2026-07-19", ["2026-06"], [3.1]))
        ingest_aggregates(db, make_aggregates("2026-07-20", ["2026-07"], [2.8]))

        target = rebuild_timeseries(db, tmp_path / "published", "finance")
        payload = json.loads(target.read_text(encoding="utf-8"))
        [series] = payload["series"]
        assert [p["label"] for p in series["points"]] == ["2026-06", "2026-07"]
        assert [p["value"] for p in series["points"]] == [3.1, 2.8]

    def test_republishing_same_date_is_idempotent(self, tmp_path: Path) -> None:
        db = tmp_path / "archive.duckdb"
        ingest_aggregates(db, make_aggregates("2026-07-20", ["2026-07"], [2.8]))
        # a correction republished for the same date replaces, not duplicates
        ingest_aggregates(db, make_aggregates("2026-07-20", ["2026-07"], [2.9]))

        target = rebuild_timeseries(db, tmp_path / "published", "finance")
        [series] = json.loads(target.read_text(encoding="utf-8"))["series"]
        assert len(series["points"]) == 1
        assert series["points"][0]["value"] == 2.9

    def test_same_label_from_two_dates_latest_wins(self, tmp_path: Path) -> None:
        db = tmp_path / "archive.duckdb"
        ingest_aggregates(db, make_aggregates("2026-07-19", ["2026-06"], [3.1]))
        ingest_aggregates(db, make_aggregates("2026-07-20", ["2026-06"], [3.0]))  # revised
        target = rebuild_timeseries(db, tmp_path / "published", "finance")
        [series] = json.loads(target.read_text(encoding="utf-8"))["series"]
        assert len(series["points"]) == 1
        assert series["points"][0]["value"] == 3.0

    def test_history_payload_limits_and_absence(self, tmp_path: Path) -> None:
        db = tmp_path / "archive.duckdb"
        assert history_payload(db, "finance") is None  # no db yet

        labels = [f"2026-{m:02d}" for m in range(1, 8)]
        ingest_aggregates(db, make_aggregates("2026-07-20", labels, [float(m) for m in range(7)]))
        payload = json.loads(history_payload(db, "finance", last_n=3) or "{}")
        [series] = payload["series"]
        assert [p["label"] for p in series["points"]] == ["2026-05", "2026-06", "2026-07"]
        assert history_payload(db, "health") is None  # other ministry: nothing


class TestPublishIntegration:
    @pytest.fixture
    def config(self, tmp_path: Path) -> AppConfig:
        cfg = AppConfig.model_validate({"brain": "fake", "ministries": ["finance"]})
        cfg.root = tmp_path
        return cfg

    def run_and_publish(self, config: AppConfig, task_id: str, created: str) -> None:
        queue = FileQueue(config.path("tasks"))
        queue.enqueue(
            TaskSpec.model_validate(
                {"id": task_id, "ministry": "finance", "type": "analysis", "created": created}
            ),
            input_files={"staging/x.parquet": b"x"},
        )
        queue.claim(task_id)
        FakeBrain().run(queue.path(QueueState.RUNNING, task_id))
        approve_marker(queue.complete(task_id))
        assert publish_all(config)["published"] == [task_id]

    def test_publish_maintains_public_timeseries(self, config: AppConfig) -> None:
        self.run_and_publish(config, "finance-2026-07-19-an", "2026-07-19T06:00:00")
        self.run_and_publish(config, "finance-2026-07-20-an", "2026-07-20T06:00:00")

        timeseries = json.loads(
            (config.path("published") / "finance" / "timeseries.json").read_text(
                encoding="utf-8"
            )
        )
        [series] = timeseries["series"]
        assert len(series["points"]) == 2  # one point per publication day
        assert (config.root / "data" / "archive.duckdb").is_file()
