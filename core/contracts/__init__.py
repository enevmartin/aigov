"""The task contract — pydantic schemas shared by core and every brain.

These models ARE the system's interface: a brain consumes a task directory
described by :class:`TaskSpec` and produces artifacts validated against
:class:`Report`, :class:`Aggregates` and :class:`NewsDigest`.
"""

from core.contracts.export import export_json_schemas
from core.contracts.models import (
    OPTIONAL_ARTIFACTS,
    REPORT_MODEL,
    REQUIRED_ARTIFACTS,
    Aggregates,
    AggregateSeries,
    Confidence,
    CrisisReport,
    HealthEvent,
    JointReport,
    NewsDigest,
    NewsItem,
    Report,
    SignalCategoryStat,
    SignalStats,
    SourceCitation,
    SourceHealth,
    SystemHealth,
    TaskSpec,
    TaskType,
)

__all__ = [
    "OPTIONAL_ARTIFACTS",
    "REPORT_MODEL",
    "REQUIRED_ARTIFACTS",
    "Aggregates",
    "AggregateSeries",
    "Confidence",
    "CrisisReport",
    "HealthEvent",
    "JointReport",
    "NewsDigest",
    "NewsItem",
    "Report",
    "SignalCategoryStat",
    "SignalStats",
    "SourceCitation",
    "SourceHealth",
    "SystemHealth",
    "TaskSpec",
    "TaskType",
    "export_json_schemas",
]
