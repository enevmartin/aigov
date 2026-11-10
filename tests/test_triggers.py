"""Media signal -> the system looks for OFFICIAL material; without it nothing
is published (чл. 8). Recorded payloads only."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from core.queue import FileQueue, QueueState
from core.triggers import detect_signals, open_signals, record_signals, respond
from core.watchers import load_watchers
from tests.support import summary
from tests.test_watchers import fake_fetch

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 10)
HEADLINES = [
    {"source_name": "Медия А", "title": "Промени в Закона за здравето", "link": "https://a.bg/1"},
    {
        "source_name": "Медия Б",
        "title": "Депутатите пипат закона за здравето",
        "link": "https://b.bg/2",
    },
]


def _signal(tmp_path: Path, keyword: str, ministry: str = "health") -> None:
    record_signals(tmp_path, detect_signals(ministry, HEADLINES, [keyword], TODAY))


def test_signal_with_official_document_becomes_event_analysis(tmp_path: Path) -> None:
    _signal(tmp_path, "здравето")
    queue = FileQueue(tmp_path / "tasks")
    [outcome] = respond(
        tmp_path,
        open_signals(tmp_path),
        load_watchers(ROOT),
        fake_fetch,
        lambda _s: [summary("health.life_expectancy")],
        queue,
        TODAY,
    )
    assert outcome["result"] == "event_analysis"
    task_dir = queue.path(QueueState.PENDING, outcome["task"])
    document = json.loads((task_dir / "input" / "document.json").read_text("utf-8"))
    assert document["url"].startswith("https://www.parliament.bg/")  # the OFFICIAL text
    trigger = json.loads((task_dir / "input" / "trigger.json").read_text("utf-8"))
    assert {t["outlet"] for t in trigger} == {"Медия А", "Медия Б"}  # media only as trigger
    assert open_signals(tmp_path) == []  # answered


def test_signal_without_official_source_publishes_nothing(tmp_path: Path) -> None:
    rumours = [
        {"source_name": "Медия А", "title": "Слух за болнична реформа", "link": "https://a.bg/3"},
        {"source_name": "Медия Б", "title": "Болничната реформа идва?", "link": "https://b.bg/4"},
    ]
    record_signals(tmp_path, detect_signals("health", rumours, ["реформа"], TODAY))
    assert len(open_signals(tmp_path)) == 1  # a real multi-outlet signal...
    queue = FileQueue(tmp_path / "tasks")
    [outcome] = respond(
        tmp_path,
        open_signals(tmp_path),
        load_watchers(ROOT),
        fake_fetch,
        lambda _s: [summary("health.life_expectancy")],
        queue,
        TODAY,
    )
    assert outcome["result"] == "no_official_source"
    assert queue.list_tasks(QueueState.PENDING) == []
    log = (tmp_path / "data" / "triggers" / "outcomes.jsonl").read_text("utf-8")
    assert "нищо не се публикува" in log


def test_signal_without_tier1_data_gets_no_document_task(tmp_path: Path) -> None:
    _signal(tmp_path, "здравето")
    queue = FileQueue(tmp_path / "tasks")
    [outcome] = respond(
        tmp_path,
        open_signals(tmp_path),
        load_watchers(ROOT),
        fake_fetch,
        lambda _s: [],
        queue,
        TODAY,
    )
    assert outcome["result"] == "no_official_source"
    assert queue.list_tasks(QueueState.PENDING) == []
