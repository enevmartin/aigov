"""DuckDB-backed series archive.

Schema (one row per data point)::

    series(ministry, date, metric, label, value, unit, source_url,
           source_title, retrieved)

``date`` is the publication date; ``label`` is the point's x-axis label
(usually a month or day). Re-publishing the same (ministry, date, metric)
replaces its rows — the archive is idempotent by design.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from core.contracts import Aggregates

_SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
    ministry     VARCHAR NOT NULL,
    date         DATE    NOT NULL,
    metric       VARCHAR NOT NULL,
    label        VARCHAR NOT NULL,
    value        DOUBLE  NOT NULL,
    unit         VARCHAR NOT NULL,
    source_url   VARCHAR NOT NULL,
    source_title VARCHAR NOT NULL,
    retrieved    DATE    NOT NULL
)
"""


def _connect(db_path: Path) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    conn.execute(_SCHEMA)
    return conn


def ingest_aggregates(db_path: Path, aggregates: Aggregates) -> int:
    """Store every point of *aggregates* in the archive; return row count.

    Idempotent: rows for the same (ministry, date, metric) are replaced, so
    re-publishing a corrected day never duplicates points.
    """
    conn = _connect(db_path)
    try:
        rows = 0
        for series in aggregates.series:
            conn.execute(
                "DELETE FROM series WHERE ministry = ? AND date = ? AND metric = ?",
                [aggregates.ministry, aggregates.date, series.name],
            )
            for label, value in zip(series.labels, series.values, strict=True):
                conn.execute(
                    "INSERT INTO series VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        aggregates.ministry,
                        aggregates.date,
                        series.name,
                        label,
                        value,
                        series.unit,
                        str(series.source.url),
                        series.source.title,
                        series.source.retrieved,
                    ],
                )
                rows += 1
        return rows
    finally:
        conn.close()


def _series_for(conn: duckdb.DuckDBPyConnection, ministry: str) -> list[dict[str, Any]]:
    """All series of *ministry*; per (metric, label) the LATEST publication wins."""
    query = """
        SELECT metric, label, value, unit, source_url, source_title, retrieved, date
        FROM (
            SELECT *, row_number() OVER (
                PARTITION BY metric, label ORDER BY date DESC
            ) AS rn
            FROM series WHERE ministry = ?
        ) WHERE rn = 1
        ORDER BY metric, label
    """
    out: dict[str, dict[str, Any]] = {}
    for metric, label, value, unit, url, title, retrieved, date in conn.execute(
        query, [ministry]
    ).fetchall():
        entry = out.setdefault(
            metric,
            {
                "name": metric,
                "unit": unit,
                "points": [],
                "source": {"url": url, "title": title, "retrieved": str(retrieved)},
            },
        )
        entry["points"].append(
            {"label": label, "value": value, "published": str(date)}
        )
    return list(out.values())


def rebuild_timeseries(db_path: Path, published_root: Path, ministry: str) -> Path:
    """Regenerate ``published/{ministry}/timeseries.json`` from the archive.

    This file IS the public institutional memory — the site charts read it.
    """
    conn = _connect(db_path)
    try:
        payload = {
            "ministry": ministry,
            "generated": datetime.now(tz=UTC).isoformat(),
            "series": _series_for(conn, ministry),
        }
    finally:
        conn.close()
    target = published_root / ministry / "timeseries.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target


def history_payload(db_path: Path, ministry: str, last_n: int = 12) -> str | None:
    """JSON for ``history.json`` task input: last *last_n* points per metric.

    Returns ``None`` when the archive has nothing for the ministry — new
    ministries simply get no history file, and the prompts handle that.
    """
    if not db_path.is_file():
        return None
    conn = _connect(db_path)
    try:
        series = _series_for(conn, ministry)
    finally:
        conn.close()
    if not series:
        return None
    for entry in series:
        entry["points"] = entry["points"][-last_n:]
    payload = {
        "ministry": ministry,
        "note": (
            "Последните публикувани стойности по показател — сравни новите данни "
            "с тенденцията: ускорение, забавяне или обрат."
        ),
        "series": series,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
