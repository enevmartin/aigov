"""The task contract — pydantic schemas shared by core and every brain.

These models ARE the system's interface: a brain consumes a task directory
described by :class:`TaskSpec` and produces artifacts validated against
:class:`Report` (numbers only as ``{{ind:<id>}}`` references, чл. 8).
"""

from core.contracts.evidence import (
    EvidenceError,
    TierRegistry,
    check_bare_numbers,
    indicator_refs,
    render_refs,
    validate_evidence,
)
from core.contracts.export import export_json_schemas
from core.contracts.models import (
    OPTIONAL_ARTIFACTS,
    REPORT_MODEL,
    REQUIRED_ARTIFACTS,
    Aggregates,
    AggregateSeries,
    Confidence,
    CorrectionRef,
    CorrectionReport,
    CrisisReport,
    DocumentRef,
    EventAnalysisReport,
    HealthEvent,
    JointReport,
    Report,
    ReviewResult,
    ReviewVerdict,
    SignalCategoryStat,
    SignalStats,
    SourceCitation,
    SourceHealth,
    SystemHealth,
    TaskSpec,
    TaskType,
)

__all__ = [
    "ReviewResult",
    "ReviewVerdict",
    "OPTIONAL_ARTIFACTS",
    "REPORT_MODEL",
    "REQUIRED_ARTIFACTS",
    "Aggregates",
    "AggregateSeries",
    "Confidence",
    "CorrectionRef",
    "CorrectionReport",
    "CrisisReport",
    "HealthEvent",
    "JointReport",
    "DocumentRef",
    "EventAnalysisReport",
    "Report",
    "SignalCategoryStat",
    "SignalStats",
    "SourceCitation",
    "SourceHealth",
    "SystemHealth",
    "TaskSpec",
    "TaskType",
    "export_json_schemas",
    "EvidenceError",
    "TierRegistry",
    "check_bare_numbers",
    "indicator_refs",
    "render_refs",
    "validate_evidence",
]
