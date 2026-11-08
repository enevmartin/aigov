"""Tier-1 indicator registry: ``ministries/{slug}/indicators.yaml`` (чл. 8).

A declaration says WHERE an official number comes from and HOW to read it;
a collector (pure Python) turns the payload into :class:`Observation` rows and
:func:`core.indicators.compute.summarize` derives every value, change and
comparison. The model never produces a number.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

MIN_INDICATORS = 5


class Frequency(StrEnum):
    DAILY = "daily"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class CollectorKind(StrEnum):
    EUROSTAT_JSONSTAT = "eurostat_jsonstat"  # API: JSON-stat 2.0
    CSV = "csv"  # tabular: long format
    XLSX = "xlsx"  # tabular: wide format (periods in a header row)


# how many days after the end of a period the next value is due, before the
# indicator is flagged stale (publication lags of official statistics)
STALE_AFTER_DAYS: dict[Frequency, int] = {
    Frequency.DAILY: 7,
    Frequency.MONTHLY: 75,
    Frequency.QUARTERLY: 200,
    Frequency.ANNUAL: 730,
}


class SourceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publisher: str = Field(min_length=1, description="e.g. Евростат, БНБ, НСИ")
    url: HttpUrl = Field(description="the dataset/API URL the collector requests")
    page: HttpUrl = Field(description="human-readable page for the site's source link")
    terms: HttpUrl | None = None
    official_api: bool


class Verification(BaseModel):
    """Result of the LIVE check (``aigov-data verify``) — never hand-written."""

    model_config = ConfigDict(extra="forbid")

    verified_at: date
    http_status: int | None
    robots: str  # "allowed" | "disallowed" | "unreachable"
    terms: str
    latest_period: str | None = None
    note: str | None = None


class IndicatorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9-]+\.[a-z0-9_]+$")
    name: str = Field(min_length=1)
    source: SourceSpec
    frequency: Frequency
    unit: str = Field(min_length=1)
    collector: CollectorKind
    params: dict[str, Any] = Field(default_factory=dict)
    rise_means: str = Field(min_length=1, description="what a rise means (neutral)")
    fall_means: str = Field(min_length=1, description="what a fall means (neutral)")
    enabled: bool = True
    disabled_reason: str | None = None
    verification: Verification | None = None

    @model_validator(mode="after")
    def _enabled_needs_live_check(self) -> IndicatorSpec:
        if not self.enabled and not self.disabled_reason:
            raise ValueError(f"{self.id}: enabled: false requires disabled_reason")
        if self.enabled:
            v = self.verification
            if v is None or v.http_status != 200 or v.robots != "allowed":
                raise ValueError(
                    f"{self.id}: an enabled indicator needs a passing live verification"
                )
        return self


class IndicatorRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ministry: str
    indicators: list[IndicatorSpec]

    @model_validator(mode="after")
    def _ids_prefixed_and_unique(self) -> IndicatorRegistry:
        ids = [i.id for i in self.indicators]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{self.ministry}: duplicate indicator ids")
        for i in ids:
            if i.split(".")[0] != self.ministry:
                raise ValueError(f"{i}: id must start with '{self.ministry}.'")
        return self

    def enabled(self) -> list[IndicatorSpec]:
        return [i for i in self.indicators if i.enabled]

    def get(self, indicator_id: str) -> IndicatorSpec | None:
        return next((i for i in self.indicators if i.id == indicator_id), None)


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    period: str  # "2026-10", "2026-Q2", "2025", "2026-11-06"
    value: float


class IndicatorSummary(BaseModel):
    """Everything the minister and the site may say about one indicator.

    Computed by :func:`core.indicators.compute.summarize` from collector rows.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    unit: str
    frequency: Frequency
    period: str
    value: float
    previous_period: str | None = None
    previous: float | None = None
    change: float | None = None
    change_pct: float | None = None
    year_ago: float | None = None
    yoy_change: float | None = None
    trend: list[Observation] = Field(default_factory=list)  # oldest -> newest
    stale: bool
    source_url: str
    source_page: str
    publisher: str
    collected_at: datetime


def registry_path(ministries_dir: Path, slug: str) -> Path:
    return ministries_dir / slug / "indicators.yaml"


def load_registry(ministries_dir: Path, slug: str) -> IndicatorRegistry | None:
    path = registry_path(ministries_dir, slug)
    if not path.is_file():
        return None
    return IndicatorRegistry.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
