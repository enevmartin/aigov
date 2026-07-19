"""The task contract — pydantic schemas shared by core and every brain.

These models ARE the system's interface: a brain consumes a task directory
described by :class:`TaskSpec` and produces artifacts validated against
:class:`Report`, :class:`Aggregates` and :class:`NewsDigest`.
"""

from core.contracts.export import export_json_schemas
from core.contracts.models import (
    Aggregates,
    AggregateSeries,
    NewsDigest,
    NewsItem,
    Report,
    SourceCitation,
    TaskSpec,
    TaskType,
)

__all__ = [
    "Aggregates",
    "AggregateSeries",
    "NewsDigest",
    "NewsItem",
    "Report",
    "SourceCitation",
    "TaskSpec",
    "TaskType",
    "export_json_schemas",
]
