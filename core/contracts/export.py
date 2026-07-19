"""Export the contract models as JSON Schema files.

Used to generate ``expected.schema.json`` inside task directories so that any
brain — including ones with no access to this Python code — can validate its
own output before handing it back.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from core.contracts.models import (
    Aggregates,
    CrisisReport,
    JointReport,
    NewsDigest,
    Report,
    SignalStats,
    SystemHealth,
    TaskSpec,
)

_EXPORTED: dict[str, type[BaseModel]] = {
    "task": TaskSpec,
    "report": Report,
    "crisis_report": CrisisReport,
    "joint_report": JointReport,
    "aggregates": Aggregates,
    "news": NewsDigest,
    "signals": SignalStats,
    "health": SystemHealth,
}


def export_json_schemas(target_dir: Path) -> list[Path]:
    """Write one ``{name}.schema.json`` per contract model into *target_dir*.

    Returns the list of files written. Idempotent: existing files are
    overwritten with the current schema.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, model in _EXPORTED.items():
        path = target_dir / f"{name}.schema.json"
        schema = model.model_json_schema()
        path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(path)
    return written
