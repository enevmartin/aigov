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
    """The kinds of work a ministry can be asked to do (all situations)."""

    ANALYSIS = "analysis"            # new statistical data arrived
    NEWS_DIGEST = "news_digest"      # daily news summary
    WEEKLY_REPORT = "weekly_report"  # Sunday consolidated report
    CRISIS_BRIEF = "crisis_brief"    # keyword spike detected by core (no LLM)
    JOINT_REPORT = "joint_report"    # "prime minister" composes published reports
    SIGNAL_TRIAGE = "signal_triage"  # citizen signals -> aggregate stats (phase 3)
    REVIEW = "review"                # second reading of another task's output


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
    # Stamped by core/publish after an approved review (never by the brain).
    reviewed: bool = False
    reviewer: str | None = None


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


class ReviewVerdict(StrEnum):
    """Outcome of a second reading."""

    APPROVE = "approve"
    REVISE = "revise"


class ReviewResult(BaseModel):
    """``review.json`` — the output of a review task.

    ``revise`` must explain itself: notes are mandatory so the original
    minister knows exactly what to fix.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: ReviewVerdict
    notes: list[str] = Field(default_factory=list)
    reviewer: str | None = None

    @model_validator(mode="after")
    def _revise_needs_notes(self) -> Self:
        if self.verdict is ReviewVerdict.REVISE and not self.notes:
            raise ValueError("a revise verdict must include concrete notes")
        return self


class Confidence(StrEnum):
    """How sure a crisis brief is that something real is happening."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CrisisReport(Report):
    """``report.md`` front-matter for a crisis_brief.

    A crisis brief must state its confidence and the keywords whose spike
    triggered it — the reader must always see WHY the system raised it.
    """

    confidence: Confidence
    trigger_keywords: list[str] = Field(min_length=1)


class JointReport(Report):
    """``report.md`` front-matter for a joint_report ("prime minister").

    Composed EXCLUSIVELY from already-published ministry reports; the
    contributors list (2+ ministries) records whose publications it uses.
    """

    contributors: list[str] = Field(min_length=2)


class SignalCategoryStat(BaseModel):
    """One anonymized category bucket of citizen signals."""

    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1)
    count: int = Field(ge=0)


class SignalStats(BaseModel):
    """``signals.json`` — the ONLY publishable form of citizen signals.

    Aggregate statistics exclusively; raw signals never leave the queue
    (чл. 5). ``total`` must equal the sum of the buckets so nothing can be
    smuggled in or out of the aggregation.
    """

    model_config = ConfigDict(extra="forbid")

    ministry: str = Field(min_length=1)
    date: Date
    total: int = Field(ge=0)
    categories: list[SignalCategoryStat]
    note: str | None = None

    @model_validator(mode="after")
    def _total_matches_buckets(self) -> Self:
        bucket_sum = sum(stat.count for stat in self.categories)
        if self.total != bucket_sum:
            raise ValueError(f"total ({self.total}) != sum of categories ({bucket_sum})")
        return self


class SourceHealth(BaseModel):
    """State of one ingest source for published/system/health.json."""

    model_config = ConfigDict(extra="forbid")

    ministry: str
    name: str
    url: str
    status: str = Field(pattern=r"^(ok|degraded)$")
    consecutive_failures: int = Field(ge=0, default=0)
    last_ok: datetime | None = None
    note: str | None = None


class HealthEvent(BaseModel):
    """One system event (data_quality_alert etc.) — generated by core, no LLM."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    kind: str = Field(min_length=1)  # e.g. "data_quality_alert", "task_failed"
    ministry: str | None = None
    message: str = Field(min_length=1)


class SystemHealth(BaseModel):
    """``published/system/health.json`` — the system's own status page data."""

    model_config = ConfigDict(extra="forbid")

    generated: datetime
    sources: list[SourceHealth] = Field(default_factory=list)
    events: list[HealthEvent] = Field(default_factory=list)
    last_session: dict[str, object] | None = None


# --- Which files each task type must (and may) produce in output/ -----------

REQUIRED_ARTIFACTS: dict[TaskType, tuple[str, ...]] = {
    TaskType.ANALYSIS: ("report.md", "aggregates.json"),
    TaskType.NEWS_DIGEST: ("report.md", "aggregates.json", "news.json"),
    TaskType.WEEKLY_REPORT: ("report.md", "aggregates.json"),
    TaskType.CRISIS_BRIEF: ("report.md",),
    TaskType.JOINT_REPORT: ("report.md",),
    TaskType.SIGNAL_TRIAGE: ("signals.json",),
    TaskType.REVIEW: ("review.json",),
}

OPTIONAL_ARTIFACTS: dict[TaskType, tuple[str, ...]] = {
    TaskType.ANALYSIS: (),
    TaskType.NEWS_DIGEST: (),
    TaskType.WEEKLY_REPORT: (),
    TaskType.CRISIS_BRIEF: ("aggregates.json",),
    TaskType.JOINT_REPORT: ("aggregates.json",),
    TaskType.SIGNAL_TRIAGE: ("report.md",),
    TaskType.REVIEW: (),
}

# Which model validates report.md front-matter for each type.
REPORT_MODEL: dict[TaskType, type[Report]] = {
    TaskType.ANALYSIS: Report,
    TaskType.NEWS_DIGEST: Report,
    TaskType.WEEKLY_REPORT: Report,
    TaskType.CRISIS_BRIEF: CrisisReport,
    TaskType.JOINT_REPORT: JointReport,
    TaskType.SIGNAL_TRIAGE: Report,
    TaskType.REVIEW: Report,  # reviews are never published; entry for completeness
}
