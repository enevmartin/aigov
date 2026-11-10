"""Shared test helpers for contract v2 (чл. 8): collector numbers as task input."""

from __future__ import annotations

import json
from typing import Any

INDICATOR_ID = "finance.hicp_annual"
SOURCE_URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_minr"
    "?geo=BG&unit=RCH_A&coicop18=TOTAL&lastTimePeriod=36&format=JSON&lang=EN"
)
SOURCE_PAGE = "https://ec.europa.eu/eurostat/databrowser/view/prc_hicp_minr/default/table?lang=en"


def summary(indicator_id: str = INDICATOR_ID, value: float = 6.0) -> dict[str, Any]:
    """A collector summary exactly as core.indicators.compute.summarize emits it."""
    return {
        "id": indicator_id,
        "name": "Инфлация (ХИПЦ), годишно изменение",
        "unit": "%",
        "frequency": "monthly",
        "period": "2026-10",
        "value": value,
        "previous_period": "2026-09",
        "previous": 5.6,
        "change": round(value - 5.6, 6),
        "change_pct": round((value - 5.6) / 5.6 * 100, 4),
        "year_ago": 3.1,
        "yoy_change": round(value - 3.1, 6),
        "trend": [
            {"period": "2026-08", "value": 5.0},
            {"period": "2026-09", "value": 5.6},
            {"period": "2026-10", "value": value},
        ],
        "stale": False,
        "source_url": SOURCE_URL,
        "source_page": SOURCE_PAGE,
        "publisher": "Евростат",
        "collected_at": "2026-11-08T06:00:00Z",
    }


def indicators_json(*summaries: dict[str, Any]) -> bytes:
    return json.dumps(list(summaries) or [summary()], ensure_ascii=False).encode()


def with_indicators(files: dict[str, bytes] | None = None) -> dict[str, bytes]:
    """Task input files plus the collector's ``indicators.json``."""
    return {**(files or {}), "indicators.json": indicators_json()}
