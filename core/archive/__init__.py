"""Institutional memory: the local DuckDB archive + public timeseries.

Every published ``aggregates.json`` lands in ``data/archive.duckdb``
(git-ignored, rebuildable); the PUBLIC archive is
``published/{ministry}/timeseries.json`` — full historical series for the
dashboard, regenerated on every publish.
"""

from core.archive.store import (
    history_payload,
    ingest_aggregates,
    rebuild_timeseries,
)

__all__ = ["history_payload", "ingest_aggregates", "rebuild_timeseries"]
