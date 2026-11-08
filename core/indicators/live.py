"""Live side of the registry: verify, record fixtures, collect.

Every request goes through :class:`core.net.PoliteClient` (robots.txt,
Crawl-delay, ``bot@aigov.bg``). A source that is broken, forbidden or does
not parse is DISABLED with the reason — never silently kept.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from core.indicators.collectors import CollectorError, parse
from core.indicators.compute import summarize
from core.indicators.models import IndicatorRegistry, IndicatorSpec, IndicatorSummary
from core.net import PoliteClient, RobotsDenied

FIXTURE_EXT = {"eurostat_jsonstat": "json", "csv": "csv", "xlsx": "xlsx"}


def verify_entry(
    entry: dict[str, Any], client: PoliteClient, today: date, fixture_dir: Path | None = None
) -> dict[str, Any]:
    """Check one raw YAML entry live; return it with ``verification`` filled.

    An entry the operator disabled for a policy reason (``disabled_reason``
    without ``verification``) is still probed, but never re-enabled here.
    """
    url = str(entry["source"]["url"])
    terms = str(entry.get("terms_verdict", "НЕПРОВЕРЕНО"))
    verification: dict[str, Any] = {"verified_at": today.isoformat(), "terms": terms}
    problem: str | None = None
    try:
        if not client.allowed(url):
            verification.update(http_status=None, robots="disallowed")
            problem = "robots.txt забранява пътя"
        else:
            response = client.get(url)
            verification.update(http_status=response.status_code, robots="allowed")
            spec = IndicatorSpec.model_validate(
                {**_without_meta(entry), "enabled": False, "disabled_reason": "probe"}
            )
            rows = parse(spec, response.content)
            verification["latest_period"] = rows[-1].period
            if fixture_dir is not None:
                ext = FIXTURE_EXT[str(entry["collector"])]
                (fixture_dir / f"{entry['id']}.{ext}").write_bytes(response.content)
    except RobotsDenied:
        verification.update(http_status=None, robots="disallowed")
        problem = "robots.txt забранява пътя"
    except httpx.HTTPStatusError as exc:
        verification.update(http_status=exc.response.status_code, robots="allowed")
        problem = f"HTTP {exc.response.status_code}"
    except httpx.HTTPError as exc:
        verification.update(http_status=None, robots="unreachable")
        problem = f"мрежова грешка: {type(exc).__name__}"
    except (CollectorError, KeyError, ValueError) as exc:
        problem = f"данните не се разчитат: {exc}"[:200]

    out = dict(entry)
    out.pop("terms_verdict", None)
    out["verification"] = verification
    if problem:
        verification["note"] = problem
        out["enabled"] = False
        out["disabled_reason"] = f"проверка на живо {today.isoformat()}: {problem}"
    return out


def verify_registry_file(
    path: Path, client: PoliteClient, today: date, fixture_dir: Path | None = None
) -> IndicatorRegistry:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["indicators"] = [verify_entry(e, client, today, fixture_dir) for e in raw["indicators"]]
    registry = IndicatorRegistry.model_validate(raw)  # enforce the contract before writing
    path.write_text(
        "# Tier-1 indicator registry (чл. 8). `verification` is written by\n"
        "# `aigov-data verify` from a LIVE check — do not edit it by hand.\n"
        + yaml.safe_dump(raw, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    return registry


def collect(
    registry: IndicatorRegistry,
    fetch: Any,
    today: date,
) -> list[IndicatorSummary]:
    """Fetch (``fetch(url) -> bytes``), parse and summarise every enabled indicator."""
    now = datetime.now(tz=UTC)
    out = []
    for spec in registry.enabled():
        rows = parse(spec, fetch(str(spec.source.url)))
        out.append(summarize(spec, rows, today, collected_at=now))
    return out


def write_summaries(summaries: list[IndicatorSummary], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([s.model_dump(mode="json") for s in summaries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _without_meta(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in entry.items()
        if k not in {"verification", "terms_verdict", "enabled", "disabled_reason"}
    }
