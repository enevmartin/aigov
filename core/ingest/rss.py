"""Generic RSS/Atom collector, configured from a ministry's declaration.

``parse_feed`` is a pure function over feed XML (fully testable offline);
``collect_rss`` drives fetching through :class:`ScraperBase` and writes the
combined result as parquet into ``data/staging/``.
"""

from __future__ import annotations

from calendar import timegm
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import feedparser
import polars as pl
from pydantic import BaseModel, ConfigDict

from core.ingest.scraper_base import ScraperBase


class FeedItem(BaseModel):
    """One normalized feed entry, ready for staging."""

    model_config = ConfigDict(extra="forbid")

    source_name: str
    source_url: str
    title: str
    link: str
    summary: str
    published: datetime | None
    retrieved: datetime


def parse_feed(
    xml: str | bytes, source_name: str, source_url: str, retrieved: datetime | None = None
) -> list[FeedItem]:
    """Parse RSS/Atom *xml* into normalized :class:`FeedItem` records.

    Entries without a title or link are skipped — they cannot be cited, and
    everything we publish must be citable.
    """
    retrieved = retrieved or datetime.now(tz=UTC)
    parsed = feedparser.parse(xml)
    items: list[FeedItem] = []
    for entry in parsed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        published: datetime | None = None
        if struct := entry.get("published_parsed") or entry.get("updated_parsed"):
            # feedparser normalizes struct_time to UTC -> timegm, NOT mktime
            # (mktime would re-interpret it in the machine's local timezone).
            published = datetime.fromtimestamp(timegm(struct), tz=UTC)
        items.append(
            FeedItem(
                source_name=source_name,
                source_url=source_url,
                title=title,
                link=link,
                summary=(entry.get("summary") or "").strip(),
                published=published,
                retrieved=retrieved,
            )
        )
    return items


def items_to_parquet(items: list[FeedItem], target: Path) -> Path:
    """Write *items* to *target* as parquet (parent dirs created)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pl.DataFrame([item.model_dump() for item in items])
    frame.write_parquet(target)
    return target


@dataclass(frozen=True)
class SourceResult:
    """Outcome of fetching one declared source (feeds the health ledger)."""

    name: str
    url: str
    ok: bool
    note: str | None = None


@dataclass(frozen=True)
class IngestResult:
    """What one ``collect_rss`` run produced."""

    staged: Path | None
    sources: list[SourceResult]
    items: int = 0


def collect_rss(
    sources: list[dict[str, str]],
    staging_dir: Path,
    ministry: str,
    scraper: ScraperBase | None = None,
) -> IngestResult:
    """Fetch every feed in *sources* and stage the combined items as parquet.

    *sources* entries need ``name`` and ``url`` keys (from ministry.yaml);
    entries with ``enabled: false`` are skipped. Individual feed failures are
    tolerated — one dead feed must not block the ministry's digest — but each
    source's outcome is reported so the health ledger can track degradation.
    """
    own_scraper = scraper is None
    scraper = scraper or ScraperBase()
    all_items: list[FeedItem] = []
    results: list[SourceResult] = []
    try:
        for source in sources:
            if not source.get("enabled", True):
                continue
            name, url = source["name"], source["url"]
            try:
                response = scraper.fetch(url)
            except Exception as exc:  # noqa: BLE001 — a dead feed is routine, not fatal
                results.append(SourceResult(name, url, ok=False, note=str(exc)))
                continue
            all_items.extend(parse_feed(response.content, name, url))
            results.append(SourceResult(name, url, ok=True))
    finally:
        if own_scraper:
            scraper.close()

    if not all_items:
        return IngestResult(staged=None, sources=results)
    stamp = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H%M%S")
    staged = items_to_parquet(all_items, staging_dir / ministry / f"rss-{stamp}.parquet")
    return IngestResult(staged=staged, sources=results, items=len(all_items))
