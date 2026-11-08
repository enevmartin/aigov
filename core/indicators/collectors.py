"""Collectors: official payload bytes -> :class:`Observation` rows (pure Python).

Two generic families, selected by ``IndicatorSpec.collector``:

- **API** — ``eurostat_jsonstat``: JSON-stat 2.0 as served by the Eurostat
  dissemination API (all non-time dimensions filtered to one value in the URL).
- **Tabular** — ``csv`` (long format: a date column, a value column, optional
  row filters) and ``xlsx`` (wide format: periods in a header row, the series
  in the row whose label matches).

Collectors parse bytes already fetched by :class:`core.net.PoliteClient` and
never touch the network or the disk themselves — fixtures plug in directly.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from core.indicators.models import CollectorKind, IndicatorSpec, Observation


class CollectorError(ValueError):
    """The payload does not have the declared shape — never guess, fail."""


def parse(spec: IndicatorSpec, payload: bytes) -> list[Observation]:
    """Dispatch to the collector declared for *spec*; rows sorted by period."""
    rows = _COLLECTORS[spec.collector](payload, spec.params)
    if not rows:
        raise CollectorError(f"{spec.id}: no observations in payload")
    return sorted(rows, key=lambda o: o.period)


# -- API: Eurostat JSON-stat 2.0 -------------------------------------------
def eurostat_jsonstat(payload: bytes, params: dict[str, Any]) -> list[Observation]:
    data = json.loads(payload)
    ids: list[str] = data["id"]
    sizes: list[int] = data["size"]
    if "time" not in ids:
        raise CollectorError("JSON-stat payload has no time dimension")
    for dim, size in zip(ids, sizes, strict=True):
        if dim != "time" and size != 1:
            raise CollectorError(f"dimension {dim!r} not filtered to one value ({size})")
    time_index: dict[str, int] = data["dimension"]["time"]["category"]["index"]
    values: dict[str, float] = data.get("value", {})
    # all other dims have size 1, so the flat index IS the time position
    return [
        Observation(period=_eurostat_period(period), value=float(values[str(pos)]))
        for period, pos in time_index.items()
        if str(pos) in values and values[str(pos)] is not None
    ]


def _eurostat_period(raw: str) -> str:
    # "2026-Q2" / "2026-10" / "2025" pass through; "2026M10" style normalised
    m = re.fullmatch(r"(\d{4})M(\d{2})", raw)
    return f"{m[1]}-{m[2]}" if m else raw


# -- Tabular: CSV (long) ----------------------------------------------------
def csv_long(payload: bytes, params: dict[str, Any]) -> list[Observation]:
    text = payload.decode(params.get("encoding", "utf-8-sig"))
    lines = text.splitlines()[int(params.get("skip_rows", 0)) :]
    reader = csv.DictReader(lines, delimiter=params.get("delimiter", ","))
    where: dict[str, str] = params.get("where", {})
    date_col, value_col = params["date_column"], params["value_column"]
    date_fmt = params.get("date_format")
    rows = []
    for row in reader:
        if any(row.get(k) != v for k, v in where.items()):
            continue
        period = row[date_col].strip()
        if date_fmt:
            period = datetime.strptime(period, date_fmt).date().isoformat()
        rows.append(Observation(period=period, value=_number(row[value_col])))
    return rows


# -- Tabular: XLSX (wide) ---------------------------------------------------
def xlsx_wide(payload: bytes, params: dict[str, Any]) -> list[Observation]:
    import openpyxl  # type: ignore[import-untyped]  # only the xlsx collector needs it

    workbook = openpyxl.load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    sheet = workbook.worksheets[int(params.get("sheet", 0))]
    grid = [list(r) for r in sheet.iter_rows(values_only=True)]
    header = grid[int(params["header_row"])]
    label = str(params["row_label"]).strip().lower()
    target = next(
        (r for r in grid if any(isinstance(c, str) and c.strip().lower() == label for c in r)),
        None,
    )
    if target is None:
        raise CollectorError(f"row {params['row_label']!r} not found")
    # the value row may be shifted vs the header (merged label cells): align
    # by aligning the LAST numeric cells of both rows
    periods = [(i, c) for i, c in enumerate(header) if isinstance(c, int | str) and _is_period(c)]
    numbers = [c for c in target[1:] if isinstance(c, int | float)]
    if len(numbers) < len(periods):
        raise CollectorError("fewer values than periods")
    numbers = numbers[-len(periods) :]
    return [
        Observation(period=str(p), value=float(v))
        for (_, p), v in zip(periods, numbers, strict=True)
    ]


def _is_period(cell: object) -> bool:
    return bool(re.fullmatch(r"\d{4}(-(Q[1-4]|\d{2}))?", str(cell)))


def _number(raw: str) -> float:
    cleaned = raw.strip().replace("\xa0", "").replace(" ", "")
    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError as exc:
        raise CollectorError(f"not a number: {raw!r}") from exc


_COLLECTORS: dict[CollectorKind, Callable[[bytes, dict[str, Any]], list[Observation]]] = {
    CollectorKind.EUROSTAT_JSONSTAT: eurostat_jsonstat,
    CollectorKind.CSV: csv_long,
    CollectorKind.XLSX: xlsx_wide,
}
