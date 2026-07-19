"""Ingest tests — fully offline: MockTransport, local XML, fake clocks."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import polars as pl
import pytest

from core.config import load_config
from core.ingest import RateLimiter, ScraperBase, collect_rss, parse_feed
from core.ingest.opendata import download_dataset
from core.ingest.scraper_base import DEFAULT_USER_AGENT, user_agent

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Икономика</title>
  <item>
    <title>БНБ запазва основния лихвен процент</title>
    <link>https://example.bg/news/1</link>
    <description>Централната банка остави ОЛП без промяна.</description>
    <pubDate>Sat, 18 Jul 2026 08:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Инфлацията се забавя до 2.6%</title>
    <link>https://example.bg/news/2</link>
    <description>НСИ отчита трети пореден месец забавяне.</description>
  </item>
  <item>
    <title></title>
    <link>https://example.bg/news/broken</link>
  </item>
</channel></rss>"""


class TestParseFeed:
    def test_parses_items_with_cyrillic(self) -> None:
        items = parse_feed(RSS_XML, "Тест медия", "https://example.bg/rss")
        assert len(items) == 2  # the titleless third entry is dropped
        assert items[0].title == "БНБ запазва основния лихвен процент"
        assert items[0].published == datetime(2026, 7, 18, 8, 0, tzinfo=UTC)
        assert items[1].published is None
        assert all(i.source_name == "Тест медия" for i in items)

    def test_uncitable_entries_skipped(self) -> None:
        xml = '<rss version="2.0"><channel><item><title>Без линк</title></item></channel></rss>'
        assert parse_feed(xml, "x", "https://example.bg/rss") == []


class TestRateLimiter:
    def test_enforces_min_interval(self) -> None:
        clock_now = [0.0]
        sleeps: list[float] = []

        def clock() -> float:
            return clock_now[0]

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            clock_now[0] += seconds

        limiter = RateLimiter(min_interval=1.5, clock=clock, sleep=sleep)
        limiter.wait()  # first call: no wait
        clock_now[0] += 0.5
        limiter.wait()  # 0.5s elapsed -> sleep 1.0
        assert sleeps == [pytest.approx(1.0)]

    def test_no_sleep_when_interval_passed(self) -> None:
        clock_now = [0.0]
        sleeps: list[float] = []
        limiter = RateLimiter(
            min_interval=1.5, clock=lambda: clock_now[0], sleep=sleeps.append
        )
        limiter.wait()
        clock_now[0] += 2.0
        limiter.wait()
        assert sleeps == []


class TestScraperBase:
    def test_sends_polite_user_agent(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["ua"] = request.headers["User-Agent"]
            return httpx.Response(200, text="ok")

        with ScraperBase(min_interval=0, transport=httpx.MockTransport(handler)) as scraper:
            scraper.fetch("https://example.bg/")
        assert seen["ua"] == DEFAULT_USER_AGENT
        assert "aigov.bg" in seen["ua"]

    def test_user_agent_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AIGOV_USER_AGENT", "custom-agent/1.0")
        assert user_agent() == "custom-agent/1.0"

    def test_http_error_raises(self) -> None:
        transport = httpx.MockTransport(lambda _: httpx.Response(500))
        with (
            ScraperBase(min_interval=0, transport=transport) as scraper,
            pytest.raises(httpx.HTTPStatusError),
        ):
            scraper.fetch("https://example.bg/")


class TestCollectRss:
    def test_stages_parquet_and_tolerates_dead_feeds(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "dead" in str(request.url):
                return httpx.Response(404)
            return httpx.Response(200, text=RSS_XML)

        scraper = ScraperBase(min_interval=0, transport=httpx.MockTransport(handler))
        sources = [
            {"name": "Жива медия", "url": "https://example.bg/rss"},
            {"name": "Мъртва медия", "url": "https://dead.example.bg/rss"},
        ]
        path = collect_rss(sources, tmp_path / "staging", "finance", scraper=scraper)
        scraper.close()

        assert path is not None and path.suffix == ".parquet"
        assert path.parent == tmp_path / "staging" / "finance"
        frame = pl.read_parquet(path)
        assert frame.height == 2
        assert frame["source_name"].unique().to_list() == ["Жива медия"]

    def test_returns_none_when_nothing_collected(self, tmp_path: Path) -> None:
        scraper = ScraperBase(
            min_interval=0, transport=httpx.MockTransport(lambda _: httpx.Response(404))
        )
        result = collect_rss(
            [{"name": "x", "url": "https://dead.example.bg/rss"}],
            tmp_path / "staging",
            "finance",
            scraper=scraper,
        )
        scraper.close()
        assert result is None
        assert not (tmp_path / "staging" / "finance").exists()


class TestOpenData:
    def test_download_with_provenance(self, tmp_path: Path) -> None:
        transport = httpx.MockTransport(lambda _: httpx.Response(200, content=b"a,b\n1,2\n"))
        scraper = ScraperBase(min_interval=0, transport=transport)
        record = download_dataset(
            "https://nsi.bg/data.csv", tmp_path / "raw", "inflation.csv", scraper=scraper
        )
        scraper.close()
        assert Path(record.path).read_bytes() == b"a,b\n1,2\n"
        assert len(record.sha256) == 64
        assert record.retrieved.tzinfo is not None


class TestConfig:
    def test_loads_repo_config(self) -> None:
        config = load_config(Path(__file__).resolve().parent.parent)
        assert config.brain == "claude_code"
        assert "finance" in [m.slug for m in config.ministries]
        assert config.brain_for("finance") == "claude_code"  # no override set
        assert config.path("tasks").name == "tasks"
        assert config.ministry_dir("finance").parts[-2:] == ("ministries", "finance")
