"""Publishing gate tests: only contract-valid output reaches published/."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config import AppConfig
from core.contracts import TaskSpec
from core.publish import publish_all, rebuild_index
from core.queue import FileQueue, QueueState
from tests.fake_brain import FakeBrain, approve_marker
from tests.support import with_indicators


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig.model_validate({"brain": "claude_code", "ministries": ["finance"]})
    cfg.root = tmp_path
    return cfg


def run_task_through_fake_brain(
    config: AppConfig, task_id: str = "finance-2026-07-19-digest", task_type: str = "analysis"
) -> FileQueue:
    queue = FileQueue(config.path("tasks"))
    spec = TaskSpec.model_validate(
        {"id": task_id, "ministry": "finance", "type": task_type, "created": "2026-07-19T06:00:00"}
    )
    queue.enqueue(spec, input_files=with_indicators({"staging/rss.parquet": b"data"}))
    running = queue.claim(task_id)
    FakeBrain().run(running)
    done = queue.complete(task_id)
    approve_marker(done)  # simulate a passed second reading
    return queue


class TestPublishAll:
    def test_valid_output_lands_in_published(self, config: AppConfig) -> None:
        queue = run_task_through_fake_brain(config)
        results = publish_all(config)

        assert results["published"] == ["finance-2026-07-19-digest"]
        target = config.path("published") / "finance" / "2026-07-19" / "analysis"
        assert (target / "report.md").is_file()
        assert (target / "indicators.json").is_file()  # the collector numbers it used
        assert not (target / "aggregates.json").exists()  # the brain never supplies numbers
        # the queue entry is gone — published/ is now the home of the artifacts
        assert queue.state_of("finance-2026-07-19-digest") is None

    def test_index_regenerated(self, config: AppConfig) -> None:
        run_task_through_fake_brain(config)
        publish_all(config)
        index = json.loads(
            (config.path("published") / "index.json").read_text(encoding="utf-8")
        )
        assert index["ministries"]["finance"][0]["date"] == "2026-07-19"
        assert "report.md" in index["ministries"]["finance"][0]["types"]["analysis"]
        # no ministries/ declarations in this fixture -> name falls back to slug
        assert index["names"]["finance"] == "finance"

    def test_invalid_output_rejected_with_reason(self, config: AppConfig) -> None:
        queue = run_task_through_fake_brain(config)
        # corrupt the report front-matter after the brain "finished"
        done_dir = queue.path(QueueState.DONE, "finance-2026-07-19-digest")
        (done_dir / "output" / "report.md").write_text(
            "---\n: [\n---\nbody", encoding="utf-8"
        )

        results = publish_all(config)
        assert results["published"] == []
        assert results["rejected"] == ["finance-2026-07-19-digest"]
        reason = (
            queue.path(QueueState.FAILED, "finance-2026-07-19-digest") / "reason.txt"
        ).read_text(encoding="utf-8")
        assert "report.md front-matter invalid" in reason
        assert not (config.path("published") / "finance").exists()

    def test_ministry_mismatch_rejected(self, config: AppConfig) -> None:
        """A brain cannot publish on behalf of another ministry."""
        queue = run_task_through_fake_brain(config)
        done_dir = queue.path(QueueState.DONE, "finance-2026-07-19-digest")
        report = (done_dir / "output" / "report.md").read_text(encoding="utf-8")
        (done_dir / "output" / "report.md").write_text(
            report.replace("ministry: finance", "ministry: defense"), encoding="utf-8"
        )

        results = publish_all(config)
        assert results["rejected"] == ["finance-2026-07-19-digest"]
        reason = (
            queue.path(QueueState.FAILED, "finance-2026-07-19-digest") / "reason.txt"
        ).read_text(encoding="utf-8")
        assert "defense" in reason and "finance" in reason

    def test_report_without_collector_numbers_is_rejected(self, config: AppConfig) -> None:
        """No tier-1 input -> no evidence -> nothing is published (чл. 8)."""
        queue = FileQueue(config.path("tasks"))
        spec = TaskSpec.model_validate(
            {"id": "finance-2026-07-19-bare", "ministry": "finance", "type": "analysis",
             "created": "2026-07-19T06:00:00"}
        )
        queue.enqueue(spec, input_files={"staging/rss.parquet": b"media items"})
        FakeBrain().run(queue.claim(spec.id))
        approve_marker(queue.complete(spec.id))
        results = publish_all(config)
        assert results["rejected"] == ["finance-2026-07-19-bare"]
        assert not (config.path("published") / "finance").exists()


class TestRebuildIndex:
    def test_empty_tree_gives_empty_index(self, tmp_path: Path) -> None:
        target = rebuild_index(tmp_path / "published")
        assert json.loads(target.read_text(encoding="utf-8")) == {
            "ministries": {},
            "names": {},
            "cabinet": [],
        }

    def test_cabinet_roster_travels_in_index(self, config: AppConfig) -> None:
        """The site shows not-yet-active ministers — the roster must be public."""
        ministry = config.ministry_dir("finance")
        ministry.mkdir(parents=True)
        (ministry / "ministry.yaml").write_text(
            'name: "Министерство на финансите"\nslug: finance\n'
            'minister_persona:\n  име: "Финвест"\n  стил: "спокоен"\n',
            encoding="utf-8",
        )
        run_task_through_fake_brain(config)
        publish_all(config)
        index = json.loads(
            (config.path("published") / "index.json").read_text(encoding="utf-8")
        )
        [entry] = index["cabinet"]
        assert entry["slug"] == "finance"
        assert entry["persona"] == "Финвест"
        assert entry["enabled"] is True

    def test_names_come_from_declarations(self, config: AppConfig, tmp_path: Path) -> None:
        ministry = config.ministry_dir("finance")
        ministry.mkdir(parents=True)
        (ministry / "ministry.yaml").write_text(
            'name: "Министерство на финансите"\nslug: finance\n', encoding="utf-8"
        )
        run_task_through_fake_brain(config)
        publish_all(config)
        index = json.loads(
            (config.path("published") / "index.json").read_text(encoding="utf-8")
        )
        assert index["names"]["finance"] == "Министерство на финансите"
