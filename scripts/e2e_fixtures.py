"""Offline end-to-end run on RECORDED official payloads (no network, no LLM).

    uv run python scripts/e2e_fixtures.py <target_root>

Builds a throw-away repo at <target_root> (config, ministries, watchers) and
runs the whole data-first pipeline with printed evidence:

    collectors (recorded tier-1 payloads) -> data/indicators/
    -> enqueue analysis per active ministry
    -> watcher (recorded parliament feed + API) -> event_analysis
    -> cabinet session with the deterministic fake brain
       (core reconciles every number BEFORE the review)
    -> publish (чл. 8 gate) -> <target_root>/published/

Then build the site against it:  (cd <target_root>/site && npx astro build)
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.cli import main as aigov  # noqa: E402
from core.config import load_config  # noqa: E402
from core.indicators import load_registry, parse, summarize  # noqa: E402
from core.indicators.live import write_summaries  # noqa: E402
from core.queue import FileQueue  # noqa: E402
from core.watchers import enqueue_event_analysis, fetch_document, load_watchers, scan  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures"
EXT = {"eurostat_jsonstat": "json", "csv": "csv", "xlsx": "xlsx"}
ACTIVE = ("finance", "health", "environment")


def recorded(url: str) -> bytes:
    if url == "https://www.parliament.bg/feed/bills":
        return (FIXTURES / "watchers" / "parliament_bills.xml").read_bytes()
    if url == "https://www.parliament.bg/api/v1/bill/167635":
        return (FIXTURES / "watchers" / "bill_167635.json").read_bytes()
    return b"<rss><channel></channel></rss>"


def main(target: Path) -> int:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name in ("config.yaml", "watchers.yaml"):
        shutil.copy(REPO / name, target / name)
    shutil.copytree(REPO / "ministries", target / "ministries")
    config = load_config(target)
    today = datetime.now(tz=UTC).date()

    print("== 1. collectors on recorded tier-1 payloads")
    for slug in ACTIVE:
        registry = load_registry(target / "ministries", slug)
        assert registry is not None
        summaries = []
        for spec in registry.enabled():
            payload = (FIXTURES / "indicators" / f"{spec.id}.{EXT[spec.collector.value]}")
            rows = parse(spec, payload.read_bytes())
            summaries.append(summarize(spec, rows, today))
        write_summaries(summaries, target / "data" / "indicators" / f"{slug}.json")
        for s in summaries:
            print(f"   {s.id:<32} {s.value:>12} {s.unit:<14} period={s.period}"
                  f" change={s.change} stale={s.stale}")

    print("== 2. enqueue analysis per active ministry (tier-1 numbers only)")
    for slug in ACTIVE:
        assert aigov(["--root", str(target), "enqueue", "--ministry", slug,
                      "--type", "analysis"]) == 0

    print("== 3. watcher: recorded parliament feed -> routed official document")
    queue = FileQueue(config.path("tasks"))
    for doc, slugs in scan(load_watchers(target), recorded, set()):
        document = fetch_document(doc, recorded, today)
        for slug in slugs:
            if slug not in ACTIVE:
                continue
            indicators = json.loads(
                (target / "data" / "indicators" / f"{slug}.json").read_text("utf-8")
            )
            task = enqueue_event_analysis(queue, slug, document, indicators)
            print(f"   [{slug}] {doc.kind}: {doc.title} -> {task}")

    print("== 4. cabinet session (fake brain; core reconciles numbers, then review)")
    assert aigov(["--root", str(target), "session", "--dry-run"]) == 0

    print("== 5. publish through the чл. 8 gate")
    assert aigov(["--root", str(target), "publish"]) == 0

    published = target / "published"
    reports = sorted(published.rglob("report.md"))
    print(f"== 6. published: {len(reports)} report(s)")
    for r in reports:
        text = r.read_text(encoding="utf-8")
        assert "{{ind:" not in text, r  # every reference was rendered from collectors
        print(f"   {r.relative_to(published).as_posix()}")
    for slug in ACTIVE:
        latest = json.loads((published / slug / "indicators.json").read_text("utf-8"))
        print(f"   published/{slug}/indicators.json: {len(latest)} tier-1 indicators")

    # the site reads <target>/published via site/src/lib (../../../published)
    shutil.copytree(REPO / "site", target / "site",
                    ignore=shutil.ignore_patterns("node_modules", "dist", ".astro"))
    print(f"== site copied to {target / 'site'} (link node_modules, then: npx astro build)")
    print(f"done {date.today().isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]).resolve()))
