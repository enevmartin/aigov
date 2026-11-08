"""Tier-1 indicators: registry contract, collectors on RECORDED fixtures, arithmetic."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from core.indicators import (
    MIN_INDICATORS,
    CollectorError,
    IndicatorRegistry,
    IndicatorSpec,
    Observation,
    is_stale,
    load_registry,
    parse,
    period_end,
    summarize,
)
from core.indicators.models import Frequency

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "indicators"
ACTIVE = ("finance", "health", "environment")
ALL = sorted(
    p.parent.name
    for p in (ROOT / "ministries").glob("*/indicators.yaml")
    if not p.parent.name.startswith("_")
)
EXT = {"eurostat_jsonstat": "json", "csv": "csv", "xlsx": "xlsx"}


def _spec(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "finance.x",
        "name": "x",
        "source": {
            "publisher": "Евростат",
            "url": "https://ec.europa.eu/x",
            "page": "https://ec.europa.eu/p",
            "official_api": True,
        },
        "frequency": "monthly",
        "unit": "%",
        "collector": "eurostat_jsonstat",
        "rise_means": "r",
        "fall_means": "f",
    }
    base.update(overrides)
    return base


# -- registry contract ----------------------------------------------------
class TestRegistryContract:
    def test_every_ministry_has_a_valid_registry(self) -> None:
        assert len(ALL) == 19
        for slug in ALL:
            assert load_registry(ROOT / "ministries", slug) is not None

    @pytest.mark.parametrize("slug", ACTIVE)
    def test_active_ministries_have_five_live_verified_tier1_indicators(self, slug: str) -> None:
        registry = load_registry(ROOT / "ministries", slug)
        assert registry is not None
        enabled = registry.enabled()
        assert len(enabled) >= MIN_INDICATORS
        for spec in enabled:
            v = spec.verification
            assert v is not None and v.http_status == 200 and v.robots == "allowed"
            assert v.latest_period, spec.id

    def test_every_declared_ministry_lists_at_least_five(self) -> None:
        for slug in ALL:
            registry = load_registry(ROOT / "ministries", slug)
            assert registry is not None and len(registry.indicators) >= MIN_INDICATORS

    def test_enabled_without_live_verification_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="live verification"):
            IndicatorSpec.model_validate(_spec())

    def test_enabled_with_robots_disallowed_is_rejected(self) -> None:
        bad = _spec(
            verification={
                "verified_at": "2026-11-08",
                "http_status": 200,
                "robots": "disallowed",
                "terms": "x",
            }
        )
        with pytest.raises(ValueError, match="live verification"):
            IndicatorSpec.model_validate(bad)

    def test_disabled_needs_a_reason(self) -> None:
        with pytest.raises(ValueError, match="disabled_reason"):
            IndicatorSpec.model_validate(_spec(enabled=False))

    def test_ids_must_carry_the_ministry_prefix(self) -> None:
        spec = _spec(enabled=False, disabled_reason="r")
        with pytest.raises(ValueError, match="must start with"):
            IndicatorRegistry.model_validate({"ministry": "health", "indicators": [spec]})


# -- collectors on recorded fixtures -----------------------------------------
def _enabled_specs() -> list[IndicatorSpec]:
    out = []
    for slug in ACTIVE:
        registry = load_registry(ROOT / "ministries", slug)
        assert registry is not None
        out.extend(registry.enabled())
    return out


@pytest.mark.parametrize("spec", _enabled_specs(), ids=lambda s: s.id)
def test_collector_parses_recorded_fixture(spec: IndicatorSpec) -> None:
    payload = (FIXTURES / f"{spec.id}.{EXT[spec.collector.value]}").read_bytes()
    rows = parse(spec, payload)
    assert rows == sorted(rows, key=lambda o: o.period)
    assert spec.verification is not None
    assert rows[-1].period == spec.verification.latest_period  # same as the live check
    summary = summarize(spec, rows, today=date(2026, 11, 8))
    assert summary.value == rows[-1].value
    assert summary.source_url == str(spec.source.url)


def test_hicp_fixture_values_match_the_payload() -> None:
    registry = load_registry(ROOT / "ministries", "finance")
    assert registry is not None
    spec = registry.get("finance.hicp_annual")
    assert spec is not None
    raw = json.loads((FIXTURES / "finance.hicp_annual.json").read_bytes())
    last_pos = max(raw["dimension"]["time"]["category"]["index"].values())
    rows = parse(spec, (FIXTURES / "finance.hicp_annual.json").read_bytes())
    assert rows[-1].value == raw["value"][str(last_pos)]


def test_jsonstat_with_unfiltered_dimension_fails_loudly() -> None:
    spec = IndicatorSpec.model_validate(_spec(enabled=False, disabled_reason="t"))
    payload = json.dumps(
        {
            "id": ["unit", "time"],
            "size": [2, 1],
            "value": {"0": 1.0},
            "dimension": {"time": {"category": {"index": {"2026-01": 0}}}},
        }
    ).encode()
    with pytest.raises(CollectorError, match="not filtered"):
        parse(spec, payload)


def test_csv_collector_filters_rows_and_parses_dates() -> None:
    spec = IndicatorSpec.model_validate(
        _spec(
            enabled=False,
            disabled_reason="t",
            collector="csv",
            frequency="daily",
            params={
                "skip_rows": 1,
                "date_column": "Дата",
                "value_column": "V",
                "date_format": "%d.%m.%Y",
                "where": {"Код": "USD"},
            },
        )
    )
    payload = 'заглавие\nДата,Код,V\n06.11.2026,USD,"1,1165"\n06.11.2026,JPY,176.7\n'.encode()
    assert parse(spec, payload) == [Observation(period="2026-11-06", value=1.1165)]


# -- arithmetic lives in Python ------------------------------------------------
def test_summary_computes_change_yoy_and_trend() -> None:
    spec = IndicatorSpec.model_validate(_spec(enabled=False, disabled_reason="t"))
    rows = [Observation(period=f"2025-{m:02d}", value=float(m)) for m in range(1, 13)]
    rows += [Observation(period="2026-01", value=20.0)]
    s = summarize(spec, rows, today=date(2026, 2, 15))
    assert (s.value, s.previous, s.change) == (20.0, 12.0, 8.0)
    assert s.change_pct == pytest.approx(66.6667, abs=1e-3)
    assert s.year_ago == 1.0 and s.yoy_change == 19.0
    assert s.trend[-1].period == "2026-01" and not s.stale


@pytest.mark.parametrize(
    ("freq", "period", "today", "stale"),
    [
        (Frequency.MONTHLY, "2026-08", date(2026, 11, 8), False),
        (Frequency.MONTHLY, "2026-01", date(2026, 11, 8), True),
        (Frequency.QUARTERLY, "2026-Q2", date(2026, 11, 8), False),
        (Frequency.ANNUAL, "2023", date(2026, 11, 8), True),
        (Frequency.DAILY, "2026-11-06", date(2026, 11, 8), False),
    ],
)
def test_staleness(freq: Frequency, period: str, today: date, stale: bool) -> None:
    assert is_stale(freq, period, today) is stale


def test_period_end() -> None:
    assert period_end("2026-Q2") == date(2026, 6, 30)
    assert period_end("2026-02") == date(2026, 2, 28)
    assert period_end("2025") == date(2025, 12, 31)


def test_registry_files_carry_no_hand_written_enabled_without_check() -> None:
    for slug in ALL:
        raw = yaml.safe_load((ROOT / "ministries" / slug / "indicators.yaml").read_text("utf-8"))
        for entry in raw["indicators"]:
            assert "verification" in entry, f"{entry['id']} was never live-checked"
