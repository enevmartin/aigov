"""Open-data / statistics downloads (CSV, JSON, HTML tables).

Raw payloads go to ``data/raw/`` (ephemeral); structured extraction into
staging parquet is the job of ministry-specific collectors configured in
``ministry.yaml`` — the transport and bookkeeping live here.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from core.ingest.scraper_base import ScraperBase


class DownloadRecord(BaseModel):
    """Provenance for one downloaded dataset — feeds source citations."""

    model_config = ConfigDict(extra="forbid")

    url: str
    path: str
    sha256: str
    retrieved: datetime


def download_dataset(
    url: str, raw_dir: Path, name: str, scraper: ScraperBase | None = None
) -> DownloadRecord:
    """Download *url* into ``{raw_dir}/{name}`` and return its provenance.

    The sha256 lets callers skip reprocessing unchanged datasets; the
    retrieval timestamp feeds the mandatory source citations.
    """
    own_scraper = scraper is None
    scraper = scraper or ScraperBase()
    try:
        response = scraper.fetch(url)
    finally:
        if own_scraper:
            scraper.close()

    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / name
    target.write_bytes(response.content)
    return DownloadRecord(
        url=url,
        path=str(target),
        sha256=hashlib.sha256(response.content).hexdigest(),
        retrieved=datetime.now(tz=UTC),
    )
