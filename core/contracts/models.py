"""Pydantic models for the file-based task contract.

Everything a brain reads (``task.yaml``) or writes (``report.md`` front-matter,
``aggregates.json``, ``news.json``) is validated against these models.
``core.publish`` is the enforcement point: invalid output never reaches
``published/``.
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class TaskType(StrEnum):
    """The kinds of work a ministry can be asked to do."""

    ANALYSIS = "analysis"
    NEWS_DIGEST = "news_digest"
    SIGNAL_TRIAGE = "signal_triage"


class TaskSpec(BaseModel):
    """``task.yaml`` — what the core asks a brain to do.

    A task is a directory ``tasks/pending/{id}/`` holding this spec, an
    ``input/`` directory with the collected data, and an
    ``expected.schema.json`` the output aggregates must satisfy.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    ministry: str = Field(min_length=1, description="Ministry slug, e.g. 'finance'")
    type: TaskType
    created: datetime
    deadline: datetime | None = None

    @model_validator(mode="after")
    def _deadline_after_created(self) -> Self:
        """A deadline before creation time is a configuration error."""
        if self.deadline is not None and self.deadline <= self.created:
            raise ValueError("deadline must be after created")
        return self


class SourceCitation(BaseModel):
    """A cited source — every published claim must trace to one of these."""

    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    title: str = Field(min_length=1)
    retrieved: Date = Field(description="Date the data/news item was retrieved")


class Report(BaseModel):
    """Front-matter of ``report.md`` — the Bulgarian-language analysis.

    The markdown body below the front-matter is free-form; this model
    validates only the structured header.
    """

    model_config = ConfigDict(extra="forbid")

    ministry: str = Field(min_length=1)
    date: Date
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1, description="1-3 sentence summary in Bulgarian")
    sources: list[SourceCitation] = Field(
        min_length=1, description="Legal guardrail: a report with no sources is invalid"
    )


class AggregateSeries(BaseModel):
    """One named numeric series for the dashboard charts."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Series name in Bulgarian, e.g. 'Инфлация (%)'")
    unit: str = Field(min_length=1, description="Unit label, e.g. '%', 'млн. лв.'")
    labels: list[str] = Field(min_length=1, description="X-axis labels (dates/categories)")
    values: list[float] = Field(min_length=1)
    source: SourceCitation

    @model_validator(mode="after")
    def _labels_match_values(self) -> Self:
        """Chart data with mismatched axes would render garbage."""
        if len(self.labels) != len(self.values):
            raise ValueError(
                f"labels ({len(self.labels)}) and values ({len(self.values)}) "
                "must have the same length"
            )
        return self


class Aggregates(BaseModel):
    """``aggregates.json`` — the numbers behind the dashboard."""

    model_config = ConfigDict(extra="forbid")

    ministry: str = Field(min_length=1)
    date: Date
    series: list[AggregateSeries] = Field(min_length=1)


class NewsItem(BaseModel):
    """One summarized news item with its source (mandatory)."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, description="Original headline (Bulgarian)")
    summary: str = Field(min_length=1, description="Neutral 1-2 sentence summary in Bulgarian")
    source: SourceCitation
    published: datetime | None = None


class NewsDigest(BaseModel):
    """``news.json`` — the daily digest for a ministry."""

    model_config = ConfigDict(extra="forbid")

    ministry: str = Field(min_length=1)
    date: Date
    items: list[NewsItem] = Field(min_length=1)
