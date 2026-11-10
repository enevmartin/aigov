"""CLI tests: the full operator flow against a temp repo, fake brain only."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.cli import main
from core.ingest.rss import FeedItem, items_to_parquet
from tests.support import indicators_json
from tests.test_ingest import RSS_XML  # noqa: F401 — reused fixture data

MINISTRY_YAML = {
    "name": "Министерство на финансите",
    "minister_persona": {"стил": "спокоен"},
    "sources": {"rss": [{"name": "Тест медия", "url": "https://example.bg/rss"}]},
}

CONFIG_YAML = {
    "brain": "claude_code",
    "brains": {"claude_code": {}},
    "ministries": ["finance"],
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A working repo root with config, one ministry, and staged data."""
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(CONFIG_YAML, allow_unicode=True), encoding="utf-8"
    )
    ministry = tmp_path / "ministries" / "finance"
    (ministry / "prompts").mkdir(parents=True)
    (ministry / "ministry.yaml").write_text(
        yaml.safe_dump(MINISTRY_YAML, allow_unicode=True), encoding="utf-8"
    )
    (ministry / "prompts" / "event_analysis.md").write_text("Документ.", encoding="utf-8")
    collected = tmp_path / "data" / "indicators"
    collected.mkdir(parents=True)
    (collected / "finance.json").write_bytes(indicators_json())  # aigov-data collect
    (ministry / "prompts" / "analysis.md").write_text("Анализирай.", encoding="utf-8")

    from datetime import UTC, datetime

    items_to_parquet(
        [
            FeedItem(
                source_name="Тест медия",
                source_url="https://example.bg/rss",
                title="Новина",
                link="https://example.bg/news/1",
                summary="…",
                published=None,
                retrieved=datetime.now(tz=UTC),
            )
        ],
        tmp_path / "data" / "staging" / "finance" / "rss-test.parquet",
    )
    return tmp_path


def run(repo: Path, *argv: str) -> int:
    return main(["--root", str(repo), *argv])


class TestOperatorFlow:
    def test_enqueue_session_publish_status(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # enqueue attaches the collector's tier-1 numbers (never media items)
        assert run(repo, "enqueue", "--ministry", "finance", "--type", "analysis") == 0
        assert "enqueued finance-" in capsys.readouterr().out
        [task] = list((repo / "tasks" / "pending").glob("finance-*"))
        assert (task / "input" / "indicators.json").is_file()
        assert not (task / "input" / "staging").exists()

        # dry-run session: fake brain, no CLI, no tokens
        assert run(repo, "session", "--dry-run") == 0
        assert "done   finance-" in capsys.readouterr().out

        # publish validates and releases
        assert run(repo, "publish") == 0
        assert "published finance-" in capsys.readouterr().out
        assert (repo / "published" / "index.json").is_file()
        published_days = [p for p in (repo / "published" / "finance").iterdir() if p.is_dir()]
        assert len(published_days) == 1
        # institutional memory refreshed alongside the publication
        assert (repo / "published" / "finance" / "timeseries.json").is_file()

        # status shows the world
        assert run(repo, "status") == 0
        out = capsys.readouterr().out
        assert "pending  0" in out
        assert "published/finance: 1 day(s)" in out

    def test_enqueue_without_collected_indicators_fails(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (repo / "data" / "indicators" / "finance.json").unlink()
        assert run(repo, "enqueue", "--ministry", "finance") == 1
        assert "no collected indicators" in capsys.readouterr().out

    def test_publish_with_nothing_done_is_ok(self, repo: Path) -> None:
        assert run(repo, "publish") == 0
