"""Grand e2e: every task type flows ingest -> queue -> fake brain -> published.

Two cabinet sessions, because weekly_report and joint_report feed on the
FIRST session's publications — exactly like production.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml

from core.cli import main
from core.config import load_config
from core.contracts import TaskSpec, TaskType
from core.ingest import ScraperBase, collect_rss
from core.queue import FileQueue
from tests.test_ingest import RSS_XML

MINISTRY_TEMPLATE = {
    "minister_persona": {"име": "Тест", "стил": "спокоен"},
    "sources": {"rss": [{"name": "Тест медия", "url": "https://example.bg/rss"}]},
    "guardrails": ["Всяко твърдение цитира източник (URL + дата на извличане)."],
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "brain": "claude_code",
                "brains": {},
                "ministries": [
                    {"slug": "finance", "enabled": True},
                    {"slug": "health", "enabled": True},
                    {"slug": "government", "enabled": True},
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    for slug in ("finance", "health", "government"):
        ministry = tmp_path / "ministries" / slug
        (ministry / "prompts").mkdir(parents=True)
        declaration = {
            "name": f"Министерство {slug}",
            "slug": slug,
            **MINISTRY_TEMPLATE,
        }
        (ministry / "ministry.yaml").write_text(
            yaml.safe_dump(declaration, allow_unicode=True), encoding="utf-8"
        )
    return tmp_path


def stage_news(repo: Path, ministry: str) -> None:
    scraper = ScraperBase(
        min_interval=0,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=RSS_XML)),
    )
    result = collect_rss(
        [{"name": "Тест медия", "url": "https://example.bg/rss"}],
        repo / "data" / "staging",
        ministry,
        scraper=scraper,
    )
    scraper.close()
    assert result.staged is not None


def enqueue_direct(repo: Path, ministry: str, task_type: str, suffix: str) -> None:
    """Bypass staging for types whose input the CLI cannot fabricate in tests."""
    queue = FileQueue(repo / "tasks")
    queue.enqueue(
        TaskSpec.model_validate(
            {
                "id": f"{ministry}-2026-07-20-{suffix}",
                "ministry": ministry,
                "type": task_type,
                "created": "2026-07-20T06:00:00",
            }
        ),
        input_files={"staging/data.parquet": b"x"},
    )


def test_every_task_type_reaches_published(repo: Path) -> None:
    run = lambda *argv: main(["--root", str(repo), *argv])  # noqa: E731

    # --- round 1: data-driven types --------------------------------------
    stage_news(repo, "finance")
    assert run("enqueue", "--ministry", "finance", "--type", "news_digest") == 0
    stage_news(repo, "finance")
    assert run("enqueue", "--ministry", "finance", "--type", "analysis") == 0
    enqueue_direct(repo, "finance", "crisis_brief", "crisis-brief")
    enqueue_direct(repo, "finance", "signal_triage", "signal-triage")
    stage_news(repo, "health")
    assert run("enqueue", "--ministry", "health", "--type", "news_digest") == 0

    assert run("session", "--dry-run") == 0
    assert run("publish") == 0

    # --- round 2: types that compose already-published reports -----------
    assert run("enqueue", "--ministry", "finance", "--type", "weekly_report") == 0
    assert run("enqueue", "--ministry", "government", "--type", "joint_report") == 0
    assert run("session", "--dry-run") == 0
    assert run("publish") == 0

    # --- everything is public, valid and indexed --------------------------
    published = repo / "published"
    index = json.loads((published / "index.json").read_text(encoding="utf-8"))
    assert set(index["ministries"]) == {"finance", "health", "government"}
    assert len(index["cabinet"]) == 3

    finance_files = {
        p.name for date in (published / "finance").iterdir() if date.is_dir()
        for p in date.iterdir()
    }
    # news_digest + analysis + weekly (report/aggregates/news) + crisis + signals
    assert {"report.md", "aggregates.json", "news.json", "signals.json"} <= finance_files

    government_report = next(
        p for date in sorted((published / "government").iterdir()) if date.is_dir()
        for p in date.iterdir() if p.name == "report.md"
    ).read_text(encoding="utf-8")
    assert "contributors:" in government_report

    # queue fully drained, nothing failed
    queue = FileQueue(repo / "tasks")
    for state in ("pending", "running", "done", "failed"):
        assert queue.list_tasks(state) == [], state

    # the session left its trace in the health ledger
    health = json.loads(
        (published / "system" / "health.json").read_text(encoding="utf-8")
    )
    assert health["last_session"]["failed"] == 0


def test_export_works_for_every_brain(repo: Path) -> None:
    """The portability contract: one declaration -> all three formats."""
    run = lambda *argv: main(["--root", str(repo), *argv])  # noqa: E731
    for brain in ("claude_code", "openclaw", "api"):
        assert run("export", "--ministry", "finance", "--brain", brain) == 0
    config = load_config(repo)
    assert (config.root / ".claude" / "agents" / "finance.md").is_file()
    assert (config.root / "export" / "openclaw" / "finance" / "skill.json").is_file()
    assert (config.root / "export" / "api" / "finance.json").is_file()
