"""CLI tests: the full operator flow against a temp repo, fake brain only."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.cli import main
from core.ingest.rss import FeedItem, items_to_parquet
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
    (ministry / "prompts" / "news.md").write_text("Резюмирай.", encoding="utf-8")
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
        # enqueue consumes staging
        assert run(repo, "enqueue", "--ministry", "finance", "--type", "news_digest") == 0
        assert "enqueued finance-" in capsys.readouterr().out
        assert not list((repo / "data" / "staging" / "finance").glob("*.parquet"))

        # dry-run session: fake brain, no CLI, no tokens
        assert run(repo, "session", "--dry-run") == 0
        assert "done   finance-" in capsys.readouterr().out

        # publish validates and releases
        assert run(repo, "publish") == 0
        assert "published finance-" in capsys.readouterr().out
        assert (repo / "published" / "index.json").is_file()
        published_days = list((repo / "published" / "finance").iterdir())
        assert len(published_days) == 1

        # status shows the world
        assert run(repo, "status") == 0
        out = capsys.readouterr().out
        assert "pending  0" in out
        assert "published/finance: 1 day(s)" in out

    def test_enqueue_without_staged_data_fails(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for p in (repo / "data" / "staging" / "finance").glob("*.parquet"):
            p.unlink()
        assert run(repo, "enqueue", "--ministry", "finance") == 1
        assert "no staged data" in capsys.readouterr().out

    def test_publish_with_nothing_done_is_ok(self, repo: Path) -> None:
        assert run(repo, "publish") == 0
