"""Tier-2 watchers on RECORDED official payloads: feed -> routed document ->
event_analysis (document + tier-1 indicators) -> fake brain -> review -> published."""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from core.config import AppConfig
from core.publish import publish_all
from core.queue import FileQueue, QueueState
from core.session import run_session
from core.watchers import (
    enqueue_event_analysis,
    fetch_document,
    load_watchers,
    route,
    scan,
)
from tests.fake_brain import FakeBrain
from tests.support import summary

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "watchers"
BILLS_FEED = "https://www.parliament.bg/feed/bills"
BILL_API = "https://www.parliament.bg/api/v1/bill/167635"


def fake_fetch(url: str) -> bytes:
    """Recorded payloads only — no network in tests."""
    if url == BILLS_FEED:
        return (FIX / "parliament_bills.xml").read_bytes()
    if url == BILL_API:
        return (FIX / "bill_167635.json").read_bytes()
    return b"<rss><channel></channel></rss>"  # other watchers: empty


def test_registry_is_live_verified_and_routes_three_active_ministries() -> None:
    reg = load_watchers(ROOT)
    enabled = {w.id for w in reg.enabled()}
    assert {"parliament.bills", "parliament.laws", "dv.issues"} <= enabled
    disabled = {w.id: w.disabled_reason for w in reg.watchers if not w.enabled}
    assert "minfin.budget" in disabled and "403" in str(disabled["minfin.budget"])
    assert {"finance", "health", "environment"} <= set(reg.routing)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Законопроект за изменение и допълнение на Закона за здравето", ["health"]),
        ("Законопроект за държавния бюджет на Република България", ["finance"]),
        ("Законопроект за управление на отпадъците", ["environment"]),
        ("Закон за ратифициране на споразумение", []),
    ],
)
def test_route(title: str, expected: list[str]) -> None:
    assert route(title, load_watchers(ROOT).routing) == expected


def test_scan_finds_routed_documents_once() -> None:
    reg = load_watchers(ROOT)
    seen: set[str] = set()
    found = scan(reg, fake_fetch, seen)
    titles = {doc.title: slugs for doc, slugs in found}
    assert titles["Законопроект за изменение и допълнение на Закона за здравето"] == ["health"]
    [health_doc] = [d for d, s in found if s == ["health"]]
    assert health_doc.api_url == BILL_API  # SPA page -> official JSON API
    assert scan(reg, fake_fetch, seen) == []  # already seen: nothing new


def test_document_text_comes_from_api_with_persons_redacted() -> None:
    reg = load_watchers(ROOT)
    [doc] = [d for d, s in scan(reg, fake_fetch, set()) if s == ["health"]]
    document = fetch_document(doc, fake_fetch, date(2026, 11, 10))
    assert "Закона за здравето" in document["text"]
    assert "MPL_Name" not in document["text"] and "imp_list" not in document["text"]
    raw = json.loads((FIX / "bill_167635.json").read_bytes())
    for mp in raw.get("imp_list", []):  # not a single name of a sponsoring MP
        assert str(mp["A_ns_MPL_Name3"]) not in document["text"]
    assert len(document["sha256"]) == 64 and document["url"].endswith("/bills/ID/167635")


def test_no_tier1_data_means_no_task(tmp_path: Path) -> None:
    queue = FileQueue(tmp_path / "tasks")
    doc = {"url": "https://www.parliament.bg/bg/bills/ID/1", "sha256": "a" * 64}
    assert enqueue_event_analysis(queue, "health", doc, []) is None
    assert queue.list_tasks(QueueState.PENDING) == []


def test_event_analysis_flows_to_published_with_tier2_source(tmp_path: Path) -> None:
    shutil.copy(ROOT / "watchers.yaml", tmp_path / "watchers.yaml")  # tier-2 registry
    config = AppConfig.model_validate({"brain": "claude_code", "ministries": ["health"]})
    config.root = tmp_path
    reg = load_watchers(ROOT)
    [doc] = [d for d, s in scan(reg, fake_fetch, set()) if s == ["health"]]
    document = fetch_document(doc, fake_fetch, date.today())
    queue = FileQueue(config.path("tasks"))
    task_id = enqueue_event_analysis(queue, "health", document, [summary("health.life_expectancy")])
    assert task_id is not None

    results = run_session(config, lambda _n: FakeBrain())
    assert results["approved"] == [task_id]  # reconciled by the core, then reviewed
    assert publish_all(config)["published"] == [task_id]

    out = next((config.path("published") / "health").glob("*/event_analysis"))
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "parliament.bg/bg/bills/ID/167635" in report  # the tier-2 document is cited
    assert "sha256:" in report and "{{ind:" not in report
    assert "text" not in json.loads((out / "indicators.json").read_text("utf-8"))[0]
