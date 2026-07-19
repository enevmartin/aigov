"""Deterministic triggers (crisis spikes) and the system health ledger."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from core.cli import main
from core.config import AppConfig
from core.ingest import detect_spike
from core.ingest.rss import FeedItem, items_to_parquet
from core.publish.health import (
    DEGRADED_AFTER,
    record_event,
    record_session,
    record_source_result,
)
from core.queue import FileQueue, QueueState


class TestDetectSpike:
    TEXTS = [
        "Банка обяви фалит след проверка",
        "Опасност от фалит на застраховател",
        "Трети случай: фалит на кредитен фонд",
        "Времето утре ще е слънчево",
    ]

    def test_spike_when_keyword_in_enough_distinct_items(self) -> None:
        trigger = detect_spike(self.TEXTS, ["фалит", "дефолт"], min_hits=3)
        assert trigger is not None
        assert trigger.keywords == ["фалит"]
        assert trigger.counts == {"фалит": 3}

    def test_no_spike_below_threshold(self) -> None:
        assert detect_spike(self.TEXTS, ["фалит"], min_hits=4) is None

    def test_repetition_inside_one_text_counts_once(self) -> None:
        texts = ["фалит фалит фалит фалит", "нищо", "пак нищо"]
        assert detect_spike(texts, ["фалит"], min_hits=2) is None

    def test_case_insensitive(self) -> None:
        texts = ["ФАЛИТ на банка", "Фалит втори", "фалит трети"]
        trigger = detect_spike(texts, ["фалит"], min_hits=3)
        assert trigger is not None

    def test_empty_keywords_never_trigger(self) -> None:
        assert detect_spike(self.TEXTS, [], min_hits=1) is None


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig.model_validate({"brain": "claude_code", "ministries": ["finance"]})
    cfg.root = tmp_path
    return cfg


class TestHealthLedger:
    SOURCE = ("finance", "Economic.bg", "https://www.economic.bg/rss/ikonomika.xml")

    def test_degraded_after_three_failures_with_single_alert(
        self, config: AppConfig
    ) -> None:
        for _ in range(DEGRADED_AFTER):
            health = record_source_result(config, *self.SOURCE, ok=False, note="HTTP 500")
        source = health.sources[0]
        assert source.status == "degraded"
        assert source.consecutive_failures == DEGRADED_AFTER

        alerts = [e for e in health.events if e.kind == "data_quality_alert"]
        assert len(alerts) == 1  # fires once, on the transition
        assert "Economic.bg" in alerts[0].message

        # one more failure -> still exactly one alert
        health = record_source_result(config, *self.SOURCE, ok=False, note="HTTP 500")
        alerts = [e for e in health.events if e.kind == "data_quality_alert"]
        assert len(alerts) == 1

    def test_success_recovers_the_source(self, config: AppConfig) -> None:
        for _ in range(DEGRADED_AFTER):
            record_source_result(config, *self.SOURCE, ok=False, note="down")
        health = record_source_result(config, *self.SOURCE, ok=True)
        source = health.sources[0]
        assert source.status == "ok"
        assert source.consecutive_failures == 0
        assert source.last_ok is not None

    def test_ledger_is_valid_published_artifact(self, config: AppConfig) -> None:
        record_event(config, "test_event", "проверка", ministry="finance")
        record_session(config, {"done": ["a"], "failed": ["b"]})
        path = config.path("published") / "system" / "health.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["last_session"]["done"] == 1
        assert payload["last_session"]["failed_ids"] == ["b"]


MINISTRY_YAML = {
    "name": "Министерство на финансите",
    "slug": "finance",
    "minister_persona": {"стил": "спокоен"},
    "sources": {"rss": [{"name": "Тест", "url": "https://example.bg/rss"}]},
    "crisis_keywords": {"min_hits": 2, "keywords": ["фалит"]},
    "guardrails": ["Всяко твърдение цитира източник."],
}


class TestCrisisAutoEnqueue:
    def make_repo(self, tmp_path: Path, titles: list[str]) -> Path:
        (tmp_path / "config.yaml").write_text(
            yaml.safe_dump(
                {"brain": "claude_code", "ministries": ["finance"], "brains": {}},
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        ministry = tmp_path / "ministries" / "finance"
        (ministry / "prompts").mkdir(parents=True)
        (ministry / "ministry.yaml").write_text(
            yaml.safe_dump(MINISTRY_YAML, allow_unicode=True), encoding="utf-8"
        )
        items = [
            FeedItem(
                source_name="Тест",
                source_url="https://example.bg/rss",
                title=title,
                link=f"https://example.bg/{i}",
                summary="…",
                published=None,
                retrieved=datetime.now(tz=UTC),
            )
            for i, title in enumerate(titles)
        ]
        items_to_parquet(items, tmp_path / "data" / "staging" / "finance" / "rss-x.parquet")
        return tmp_path

    def test_spike_enqueues_crisis_task_with_trigger_metadata(self, tmp_path: Path) -> None:
        from core.cli import _maybe_enqueue_crisis
        from core.config import load_config

        repo = self.make_repo(tmp_path, ["Фалит на банка", "Втори фалит", "Друго"])
        config = load_config(repo)
        staged = repo / "data" / "staging" / "finance" / "rss-x.parquet"
        _maybe_enqueue_crisis(config, "finance", staged)

        queue = FileQueue(config.path("tasks"))
        [task_id] = queue.list_tasks(QueueState.PENDING)
        assert task_id.endswith("-crisis-brief")
        task_dir = queue.path(QueueState.PENDING, task_id)
        trigger = json.loads((task_dir / "input" / "trigger.json").read_text(encoding="utf-8"))
        assert trigger["keywords"] == ["фалит"]
        # input carries a COPY: the staged parquet stays for the daily digest
        assert staged.exists()

        # same-day second trigger is a no-op, not an error
        _maybe_enqueue_crisis(config, "finance", staged)
        assert len(queue.list_tasks(QueueState.PENDING)) == 1

    def test_no_spike_no_task(self, tmp_path: Path) -> None:
        from core.cli import _maybe_enqueue_crisis
        from core.config import load_config

        repo = self.make_repo(tmp_path, ["Спокоен ден", "Нищо ново"])
        config = load_config(repo)
        _maybe_enqueue_crisis(
            config, "finance", repo / "data" / "staging" / "finance" / "rss-x.parquet"
        )
        queue = FileQueue(config.path("tasks"))
        assert queue.list_tasks(QueueState.PENDING) == []


def test_session_records_health_summary(tmp_path: Path) -> None:
    """aigov session leaves its summary in the health ledger."""
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {"brain": "claude_code", "ministries": ["finance"], "brains": {}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (tmp_path / "ministries" / "finance" / "prompts").mkdir(parents=True)
    assert main(["--root", str(tmp_path), "session", "--dry-run"]) == 0
    payload = json.loads(
        (tmp_path / "published" / "system" / "health.json").read_text(encoding="utf-8")
    )
    assert payload["last_session"]["done"] == 0
    assert payload["last_session"]["failed"] == 0
