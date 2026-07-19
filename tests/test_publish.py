"""Publishing gate tests: only contract-valid output reaches published/."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config import AppConfig
from core.contracts import TaskSpec
from core.publish import publish_all, rebuild_index
from core.queue import FileQueue, QueueState
from tests.fake_brain import FakeBrain


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig.model_validate({"brain": "claude_code", "ministries": ["finance"]})
    cfg.root = tmp_path
    return cfg


def run_task_through_fake_brain(
    config: AppConfig, task_id: str = "finance-2026-07-19-digest", task_type: str = "news_digest"
) -> FileQueue:
    queue = FileQueue(config.path("tasks"))
    spec = TaskSpec.model_validate(
        {"id": task_id, "ministry": "finance", "type": task_type, "created": "2026-07-19T06:00:00"}
    )
    queue.enqueue(spec, input_files={"staging/rss.parquet": b"data"})
    running = queue.claim(task_id)
    FakeBrain().run(running)
    queue.complete(task_id)
    return queue


class TestPublishAll:
    def test_valid_output_lands_in_published(self, config: AppConfig) -> None:
        queue = run_task_through_fake_brain(config)
        results = publish_all(config)

        assert results["published"] == ["finance-2026-07-19-digest"]
        target = config.path("published") / "finance" / "2026-07-19"
        assert (target / "report.md").is_file()
        assert (target / "aggregates.json").is_file()
        assert (target / "news.json").is_file()
        # the queue entry is gone — published/ is now the home of the artifacts
        assert queue.state_of("finance-2026-07-19-digest") is None

    def test_index_regenerated(self, config: AppConfig) -> None:
        run_task_through_fake_brain(config)
        publish_all(config)
        index = json.loads(
            (config.path("published") / "index.json").read_text(encoding="utf-8")
        )
        assert index["ministries"]["finance"][0]["date"] == "2026-07-19"
        assert "report.md" in index["ministries"]["finance"][0]["artifacts"]
        # no ministries/ declarations in this fixture -> name falls back to slug
        assert index["names"]["finance"] == "finance"

    def test_invalid_output_rejected_with_reason(self, config: AppConfig) -> None:
        queue = run_task_through_fake_brain(config)
        # corrupt the aggregates after the brain "finished"
        done_dir = queue.path(QueueState.DONE, "finance-2026-07-19-digest")
        (done_dir / "output" / "aggregates.json").write_text("{not json", encoding="utf-8")

        results = publish_all(config)
        assert results["published"] == []
        assert results["rejected"] == ["finance-2026-07-19-digest"]
        reason = (
            queue.path(QueueState.FAILED, "finance-2026-07-19-digest") / "reason.txt"
        ).read_text(encoding="utf-8")
        assert "aggregates.json invalid" in reason
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

    def test_news_digest_without_news_json_rejected(self, config: AppConfig) -> None:
        queue = run_task_through_fake_brain(config)
        done_dir = queue.path(QueueState.DONE, "finance-2026-07-19-digest")
        (done_dir / "output" / "news.json").unlink()

        results = publish_all(config)
        assert results["rejected"] == ["finance-2026-07-19-digest"]
        reason = (
            queue.path(QueueState.FAILED, "finance-2026-07-19-digest") / "reason.txt"
        ).read_text(encoding="utf-8")
        assert "news.json" in reason

    def test_analysis_task_needs_no_news_json(self, config: AppConfig) -> None:
        run_task_through_fake_brain(config, "finance-2026-07-19-an", "analysis")
        results = publish_all(config)
        assert results["published"] == ["finance-2026-07-19-an"]
        target = config.path("published") / "finance" / "2026-07-19"
        assert not (target / "news.json").exists()


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
