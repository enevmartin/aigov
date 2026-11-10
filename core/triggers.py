"""Media (tier 3) are a TRIGGER only — never evidence (чл. 8).

1. :func:`detect_signals` — a ministry keyword that appears in headlines of
   at least ``min_outlets`` DIFFERENT outlets in one ingest batch is a signal.
2. :func:`record_signals` — signals are logged to ``data/triggers/`` (aggregate
   metadata: keyword, outlets, headline links), nothing is enqueued.
3. :func:`respond` — for each open signal the system looks for OFFICIAL
   material on the topic: a tier-2 document in the watchers' feeds (->
   ``event_analysis``), else a tier-1 indicator whose name matches (->
   ``analysis``). Media headlines travel only as ``trigger.json``. If no
   tier-1/2 material exists, the outcome is logged and NOTHING is published.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from core.contracts import TaskSpec, TaskType
from core.queue import FileQueue
from core.watchers.watch import (
    Document,
    WatcherRegistry,
    _api_url,
    enqueue_event_analysis,
    fetch_document,
    parse_feed,
)

MIN_OUTLETS = 2
SIGNALS_FILE = "signals.jsonl"
OUTCOMES_FILE = "outcomes.jsonl"
Fetch = Callable[[str], bytes]


@dataclass
class MediaSignal:
    ministry: str
    keyword: str
    outlets: list[str]
    headlines: list[dict[str, str]] = field(default_factory=list)
    detected: str = ""

    @property
    def key(self) -> str:
        return f"{self.detected}:{self.ministry}:{self.keyword}"


def detect_signals(
    ministry: str,
    items: Iterable[Mapping[str, Any]],
    keywords: Iterable[str],
    today: date,
    min_outlets: int = MIN_OUTLETS,
) -> list[MediaSignal]:
    """Keywords present in titles/summaries from >= *min_outlets* distinct outlets."""
    rows = list(items)
    out = []
    for keyword in keywords:
        needle = keyword.lower().strip()
        if not needle:
            continue
        hits = [r for r in rows if needle in f"{r.get('title', '')} {r.get('summary', '')}".lower()]
        outlets = sorted({str(r.get("source_name", "")) for r in hits})
        if len(outlets) >= min_outlets:
            heads = [
                {
                    "title": str(r["title"]),
                    "url": str(r.get("link", "")),
                    "outlet": str(r.get("source_name", "")),
                }
                for r in hits
            ]
            out.append(MediaSignal(ministry, keyword, outlets, heads, today.isoformat()))
    return out


def record_signals(root: Path, signals: Iterable[MediaSignal]) -> list[MediaSignal]:
    """Append NEW signals (one per ministry/keyword/day) to data/triggers/."""
    path = root / "data" / "triggers" / SIGNALS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    known = {json.loads(line)["key"] for line in _lines(path)}
    fresh = [s for s in signals if s.key not in known]
    with path.open("a", encoding="utf-8") as fh:
        for s in fresh:
            fh.write(json.dumps({"key": s.key, **asdict(s)}, ensure_ascii=False) + "\n")
    return fresh


def open_signals(root: Path) -> list[MediaSignal]:
    """Recorded signals that have no outcome yet."""
    base = root / "data" / "triggers"
    done = {json.loads(line)["key"] for line in _lines(base / OUTCOMES_FILE)}
    out = []
    for line in _lines(base / SIGNALS_FILE):
        raw = json.loads(line)
        raw.pop("key")
        signal = MediaSignal(**raw)
        if signal.key not in done:
            out.append(signal)
    return out


def respond(
    root: Path,
    signals: Iterable[MediaSignal],
    watchers: WatcherRegistry,
    fetch: Fetch,
    indicators_for: Callable[[str], list[dict[str, Any]]],
    queue: FileQueue,
    today: date,
) -> list[dict[str, str]]:
    """Look for tier-2 then tier-1 material per signal; log every outcome."""
    feeds = {str(w.url): (w, parse_feed(fetch(str(w.url)), str(w.url))) for w in watchers.enabled()}
    outcomes = []
    for signal in signals:
        trigger = signal.headlines
        indicators = indicators_for(signal.ministry)
        outcome: dict[str, str] = {
            "key": signal.key,
            "ministry": signal.ministry,
            "keyword": signal.keyword,
        }
        doc = _find_document(signal.keyword, feeds)
        if doc is not None and indicators:
            document = fetch_document(doc, fetch, today)
            task = enqueue_event_analysis(queue, signal.ministry, document, indicators, trigger)
            outcome.update(result="event_analysis", task=task or "", source=doc.url)
        elif any(signal.keyword.lower() in str(i.get("name", "")).lower() for i in indicators):
            task = _enqueue_analysis(queue, signal.ministry, indicators, trigger)
            outcome.update(result="analysis", task=task or "")
        else:
            outcome.update(
                result="no_official_source",
                note="няма намерен източник от ниво 1/2 — нищо не се публикува",
            )
        outcomes.append(outcome)
    path = root / "data" / "triggers" / OUTCOMES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for o in outcomes:
            fh.write(json.dumps(o, ensure_ascii=False) + "\n")
    return outcomes


def _find_document(
    keyword: str, feeds: Mapping[str, tuple[Any, list[tuple[str, str]]]]
) -> Document | None:
    needle = keyword.lower()
    for watcher, items in feeds.values():
        for link, title in items:
            if needle in title.lower():
                return Document(
                    link,
                    title,
                    watcher.publisher,
                    watcher.kind,
                    watcher.id,
                    api_url=_api_url(watcher, link),
                    redact=tuple(watcher.redact),
                )
    return None


def _enqueue_analysis(
    queue: FileQueue,
    ministry: str,
    indicators: list[dict[str, Any]],
    trigger: list[dict[str, str]],
) -> str | None:
    now = datetime.now(tz=UTC)
    spec = TaskSpec(
        id=f"{ministry}-{now:%Y-%m-%d-%H%M%S}-signal-analysis",
        ministry=ministry,
        type=TaskType.ANALYSIS,
        created=now,
    )
    try:
        queue.enqueue(
            spec,
            input_files={
                "indicators.json": json.dumps(indicators, ensure_ascii=False, indent=2).encode(),
                "trigger.json": json.dumps(trigger, ensure_ascii=False, indent=2).encode(),
            },
        )
    except FileExistsError:
        return None
    return spec.id


def _lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
