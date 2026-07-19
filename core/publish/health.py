"""System health ledger: ``published/system/health.json``.

Written EXCLUSIVELY by the core (no LLM involved) — data_quality_alert
events, per-source degradation state, and the last session summary. The
site's /system page renders this file; like everything under ``published/``
it is static output.

A source becomes ``degraded`` after 3 consecutive failures (чл. фаза-2
стъпка 3.3) and recovers to ``ok`` on the first success.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from core.config import AppConfig
from core.contracts import HealthEvent, SourceHealth, SystemHealth

HEALTH_DIR = "system"
HEALTH_FILE = "health.json"
DEGRADED_AFTER = 3  # consecutive failures
MAX_EVENTS = 200  # keep the ledger bounded


def health_path(config: AppConfig) -> Path:
    """Location of health.json under published/."""
    return config.path("published") / HEALTH_DIR / HEALTH_FILE


def load_health(config: AppConfig) -> SystemHealth:
    """Read the current ledger (empty one if the file does not exist yet)."""
    path = health_path(config)
    if path.is_file():
        return SystemHealth.model_validate_json(path.read_text(encoding="utf-8"))
    return SystemHealth(generated=datetime.now(tz=UTC))


def _save(config: AppConfig, health: SystemHealth) -> Path:
    health.generated = datetime.now(tz=UTC)
    health.events = health.events[-MAX_EVENTS:]
    path = health_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        health.model_dump_json(indent=2, exclude_none=True) + "\n", encoding="utf-8"
    )
    return path


def record_source_result(
    config: AppConfig, ministry: str, name: str, url: str, ok: bool, note: str | None = None
) -> SystemHealth:
    """Record one fetch attempt; raise a data_quality_alert on degradation.

    The alert fires exactly once per degradation (on the transition to
    ``degraded``), not on every subsequent failure.
    """
    health = load_health(config)
    source = next(
        (s for s in health.sources if s.ministry == ministry and s.url == url), None
    )
    if source is None:
        source = SourceHealth(ministry=ministry, name=name, url=url, status="ok")
        health.sources.append(source)

    if ok:
        source.consecutive_failures = 0
        source.status = "ok"
        source.last_ok = datetime.now(tz=UTC)
        source.note = None
    else:
        source.consecutive_failures += 1
        source.note = note
        if source.consecutive_failures >= DEGRADED_AFTER and source.status != "degraded":
            source.status = "degraded"
            health.events.append(
                HealthEvent(
                    timestamp=datetime.now(tz=UTC),
                    kind="data_quality_alert",
                    ministry=ministry,
                    message=(
                        f"източник '{name}' е недостъпен "
                        f"{source.consecutive_failures} поредни пъти ({url})"
                    ),
                )
            )
    _save(config, health)
    return health


def record_event(
    config: AppConfig, kind: str, message: str, ministry: str | None = None
) -> SystemHealth:
    """Append a system event (task failures, anomalies) to the ledger."""
    health = load_health(config)
    health.events.append(
        HealthEvent(
            timestamp=datetime.now(tz=UTC), kind=kind, ministry=ministry, message=message
        )
    )
    _save(config, health)
    return health


def record_session(config: AppConfig, results: dict[str, list[str]]) -> SystemHealth:
    """Store the last cabinet-session summary for the /system page."""
    health = load_health(config)
    health.last_session = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "done": len(results.get("done", [])),
        "failed": len(results.get("failed", [])),
        "failed_ids": results.get("failed", []),
    }
    _save(config, health)
    return health
