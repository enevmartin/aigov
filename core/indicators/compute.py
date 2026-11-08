"""All arithmetic on official numbers lives HERE, never in a prompt (чл. 8)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from core.indicators.models import (
    STALE_AFTER_DAYS,
    Frequency,
    IndicatorSpec,
    IndicatorSummary,
    Observation,
)

TREND_POINTS = {
    Frequency.DAILY: 30,
    Frequency.MONTHLY: 24,
    Frequency.QUARTERLY: 12,
    Frequency.ANNUAL: 10,
}
YEAR_AGO_LAG = {
    Frequency.DAILY: 365,
    Frequency.MONTHLY: 12,
    Frequency.QUARTERLY: 4,
    Frequency.ANNUAL: 1,
}


def summarize(
    spec: IndicatorSpec,
    rows: list[Observation],
    today: date,
    collected_at: datetime | None = None,
) -> IndicatorSummary:
    """Latest value, change vs previous period, year-ago comparison, trend, staleness."""
    rows = sorted(rows, key=lambda o: o.period)
    last = rows[-1]
    prev = rows[-2] if len(rows) > 1 else None
    year_ago = _year_ago(spec.frequency, rows)
    change = round(last.value - prev.value, 6) if prev else None
    change_pct = (
        round((last.value - prev.value) / abs(prev.value) * 100, 4)
        if prev and prev.value != 0
        else None
    )
    return IndicatorSummary(
        id=spec.id,
        name=spec.name,
        unit=spec.unit,
        frequency=spec.frequency,
        period=last.period,
        value=last.value,
        previous_period=prev.period if prev else None,
        previous=prev.value if prev else None,
        change=change,
        change_pct=change_pct,
        year_ago=year_ago.value if year_ago else None,
        yoy_change=round(last.value - year_ago.value, 6) if year_ago else None,
        trend=rows[-TREND_POINTS[spec.frequency] :],
        stale=is_stale(spec.frequency, last.period, today),
        source_url=str(spec.source.url),
        source_page=str(spec.source.page),
        publisher=spec.source.publisher,
        collected_at=collected_at or datetime.now(tz=UTC),
    )


def _year_ago(freq: Frequency, rows: list[Observation]) -> Observation | None:
    if freq is Frequency.DAILY:
        target = period_end(rows[-1].period).replace(year=period_end(rows[-1].period).year - 1)
        older = [o for o in rows if period_end(o.period) <= target]
        return older[-1] if older else None
    lag = YEAR_AGO_LAG[freq]
    return rows[-1 - lag] if len(rows) > lag else None


def period_end(period: str) -> date:
    """Last day covered by a period string."""
    if len(period) == 4:
        return date(int(period), 12, 31)
    year = int(period[:4])
    if "-Q" in period:
        q = int(period[-1])
        month = q * 3
    elif len(period) == 7:
        month = int(period[5:7])
    else:
        return date.fromisoformat(period)
    next_month = date(year + (month == 12), month % 12 + 1, 1)
    return date.fromordinal(next_month.toordinal() - 1)


def is_stale(freq: Frequency, period: str, today: date) -> bool:
    return (today - period_end(period)).days > STALE_AFTER_DAYS[freq]
