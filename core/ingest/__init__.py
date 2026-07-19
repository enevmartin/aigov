"""Data collection: RSS feeds, HTML scraping, open-data downloads.

Pure Python, brain-independent, free to run continuously. Collected items
land as parquet in ``data/staging/`` (structured) and raw payloads in
``data/raw/`` (ephemeral, git-ignored, deleted after processing).
"""

from core.ingest.crisis import CrisisTrigger, detect_spike
from core.ingest.rss import FeedItem, IngestResult, SourceResult, collect_rss, parse_feed
from core.ingest.scraper_base import RateLimiter, ScraperBase

__all__ = [
    "CrisisTrigger",
    "FeedItem",
    "IngestResult",
    "RateLimiter",
    "ScraperBase",
    "SourceResult",
    "collect_rss",
    "detect_spike",
    "parse_feed",
]
