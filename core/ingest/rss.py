"""Generic RSS/Atom collector, configured from a ministry's declaration.

``parse_feed`` is a pure function over feed XML (fully testable offline);
``collect_rss`` drives fetching through :class:`ScraperBase` and writes the
combined result as parquet into ``data/staging/``.
"""

from __future__ import annotations

from calendar import timegm
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


def collect_rss(
    sources: list[dict[str, str]],
    staging_dir: Path,
    ministry: str,
    scraper: ScraperBase | None = None,
) -> Path | None:
    """Fetch every feed in *sources* and stage the combined items as parquet.

    *sources* entries need ``name`` and ``url`` keys (from ministry.yaml).
    Returns the parquet path, or ``None`` when no items were collected.
    Individual feed failures are tolerated: one dead feed must not block the
    ministry's digest.
    """
    own_scraper = scraper is None
    scraper = scraper or ScraperBase()
    all_items: list[FeedItem] = []
    try:
        for source in sources:
            try:
                response = scraper.fetch(source["url"])
            except Exception:  # noqa: BLE001 — a dead feed is routine, not fatal
                continue
            all_items.extend(parse_feed(response.content, source["name"], source["url"]))
    finally:
        if own_scraper:
            scraper.close()

    if not all_items:
        return None
    stamp = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H%M%S")
    return items_to_parquet(all_items, staging_dir / ministry / f"rss-{stamp}.parquet")
