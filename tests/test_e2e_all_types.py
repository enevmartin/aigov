"""Grand e2e: every task type flows collector -> queue -> fake brain -> published.

Two cabinet sessions, because weekly_report and joint_report feed on the
FIRST session's publications — exactly like production.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from core.cli import main
from core.config import load_config
from core.contracts import TaskSpec
from core.queue import FileQueue
from tests.support import indicators_json, summary, with_indicators

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


def collect(repo: Path, ministry: str) -> None:
    """What `aigov-data collect` leaves behind: tier-1 summaries per ministry."""
    target = repo / "data" / "indicators" / f"{ministry}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(indicators_json(summary(f"{ministry}.indicator_a")))


DOCUMENT = {
    "url": "https://www.parliament.bg/bg/bills/ID/1",
    "title": "Законопроект за държавния бюджет",
    "publisher": "Народно събрание",
    "kind": "законопроект",
    "retrieved": "2026-11-08",
    "sha256": "c" * 64,
    "text": "Член първи.",
}


def enqueue_direct(repo: Path, ministry: str, task_type: str, suffix: str, today: datetime) -> None:
    """Bypass staging for types whose input the CLI cannot fabricate in tests.

    *today* is injected from the same clock the CLI uses, so these tasks and
    the CLI-enqueued ones land on one publication day whatever the system date.
    """
    queue = FileQueue(repo / "tasks")
    queue.enqueue(
        TaskSpec.model_validate(
            {
                "id": f"{ministry}-{today:%Y-%m-%d}-{suffix}",
                "ministry": ministry,
                "type": task_type,
                "created": today.replace(tzinfo=None).isoformat(timespec="seconds"),
            }
        ),
        input_files=with_indicators(
            {"document.json": json.dumps(DOCUMENT, ensure_ascii=False).encode()}
            if task_type == "event_analysis"
            else {}
        ),
    )


def test_every_task_type_reaches_published(repo: Path) -> None:
    run = lambda *argv: main(["--root", str(repo), *argv])  # noqa: E731
    today = datetime.now(tz=UTC)  # injected today: the CLI's own clock

    # --- round 1: data-driven types (tier-1 numbers from the collectors) -----
    for slug in ("finance", "health"):
        collect(repo, slug)
    assert run("enqueue", "--ministry", "finance", "--type", "analysis") == 0
    enqueue_direct(repo, "finance", "event_analysis", "event-analysis", today)
    enqueue_direct(repo, "finance", "crisis_brief", "crisis-brief", today)
    enqueue_direct(repo, "finance", "signal_triage", "signal-triage", today)
    assert run("enqueue", "--ministry", "health", "--type", "analysis") == 0

    assert run("session", "--dry-run") == 0
    assert run("publish") == 0

    # --- round 2: types that compose already-published reports -----------
    assert run("enqueue", "--ministry", "finance", "--type", "weekly_report") == 0
    assert run("enqueue", "--ministry", "government", "--type", "joint_report") == 0
    assert run("enqueue", "--ministry", "finance", "--type", "plan") == 0
    assert run("session", "--dry-run") == 0
    assert run("publish") == 0

    # --- round 3: the operator orders a correction of a published day ----
    # target the day that actually holds the analysis — never "the first day",
    # which depended on the system date (AUDIT-2026-11 F-06)
    digest_days = sorted(p.parent.name for p in (repo / "published" / "finance").glob("*/analysis"))
    assert digest_days, "round 1 published no finance analysis"
    assert (
        run(
            "correct",
            "finance",
            digest_days[0],
            "--type",
            "analysis",
            "--note",
            "грешно число",
        )
        == 0
    )
    assert run("session", "--dry-run") == 0
    assert run("publish") == 0

    # --- everything is public, valid and indexed --------------------------
    published = repo / "published"
    index = json.loads((published / "index.json").read_text(encoding="utf-8"))
    assert set(index["ministries"]) == {"finance", "health", "government"}
    assert len(index["cabinet"]) == 3

    finance_types = {
        type_dir.name
        for date in (published / "finance").iterdir()
        if date.is_dir()
        for type_dir in date.iterdir()
        if type_dir.is_dir()
    }
    # each publication type lives in its own subdir — no same-day clobbering
    assert {
        "analysis",
        "event_analysis",
        "crisis_brief",
        "signal_triage",
        "weekly_report",
        "plan",
        "correction",
    } <= finance_types

    government_report = next(
        p for p in sorted((published / "government").rglob("report.md"))
    ).read_text(encoding="utf-8")
    assert "contributors:" in government_report

    # every published report carries the second-reading stamp
    for report_path in published.rglob("report.md"):
        assert "reviewed: true" in report_path.read_text(encoding="utf-8"), report_path

    # чл. 8: published numbers are the collector's, rendered from references
    analysis = next((published / "finance").glob("*/analysis/report.md")).read_text("utf-8")
    assert "{{ind:" not in analysis and "6 %" in analysis
    assert (published / "finance" / "indicators.json").is_file()

    # the corrected original gained its sidecar; institutional memory exists
    assert list(published.rglob("corrected_by.json")), "correction sidecar missing"
    assert (published / "finance" / "timeseries.json").is_file()
    assert (published / "system" / "sessions.json").is_file()

    # queue fully drained, nothing failed
    queue = FileQueue(repo / "tasks")
    for state in ("pending", "running", "done", "failed"):
        assert queue.list_tasks(state) == [], state

    # the session left its trace in the health ledger
    health = json.loads((published / "system" / "health.json").read_text(encoding="utf-8"))
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
