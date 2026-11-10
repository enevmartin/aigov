"""Чл. 8 in code: numbers only from collectors, evidence only from tiers 1-2.

A report may mention a number ONLY as a reference ``{{ind:<id>}}`` or
``{{ind:<id>.<field>}}`` to an indicator present in the task's
``input/indicators.json`` (computed by Python collectors). Any other digit
in the prose is rejected, except a closed grammar of non-quantities: years,
dates, periods and legal references ("чл. 45", "ДВ бр. 43", "§ 12").

The TIER of a source URL is decided by the registry — never by the model:

- tier 1: a URL (dataset or page) declared in some ``indicators.yaml``;
- tier 2: a host of an official-document watcher (``watchers.yaml``);
- anything else is tier 3 (media/unknown) and may appear only under the
  report's ``trigger:`` — as ``sources`` it is rejected.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

REF_FIELDS = (
    "value",
    "change",
    "change_pct",
    "yoy_change",
    "previous",
    "year_ago",
    "period",
    "previous_period",
)
REF = re.compile(r"\{\{ind:([a-z0-9-]+\.[a-z0-9_]+)(?:\.(" + "|".join(REF_FIELDS) + r"))?\}\}")

# non-quantities a minister may write with digits (order matters: longest first)
_ALLOWED = [
    r"\b\d{1,2}\.\d{1,2}\.(?:19|20)\d{2}\s*г?\.?",  # 06.11.2026 г.
    r"\b(?:19|20)\d{2}-\d{2}(?:-\d{2})?\b",  # 2026-11 / 2026-11-08
    r"\b(?:19|20)\d{2}-Q[1-4]\b",  # 2026-Q2
    r"\bQ[1-4]\b",
    r"(?:чл|ал|т|бр|стр|гл|разд|прил|точка|алинея|член)\.?\s*\d+[а-я]?",  # legal refs
    r"[§№]\s*\d+",
    r"\b(?:19|20)\d{2}\b",  # a year
]
_ALLOWED_RE = re.compile("|".join(_ALLOWED), re.IGNORECASE)
_DIGIT = re.compile(r"\d[\d\s.,]*%?")


class EvidenceError(ValueError):
    """The report breaks чл. 8 — it must not be published."""


def indicator_refs(text: str) -> list[tuple[str, str]]:
    """All ``(indicator_id, field)`` references in *text*."""
    return [(m[1], m[2] or "value") for m in REF.finditer(text)]


def check_bare_numbers(text: str) -> list[str]:
    """Digits in *text* that are neither references nor allowed non-quantities."""
    stripped = REF.sub(" ", text)
    stripped = re.sub(r"`[^`]*`", " ", stripped)  # code spans: ids, not claims
    stripped = re.sub(r"https?://\S+", " ", stripped)  # URLs
    stripped = _ALLOWED_RE.sub(" ", stripped)
    return [m.group().strip() for m in _DIGIT.finditer(stripped)]


@dataclass
class TierRegistry:
    tier1_urls: set[str] = field(default_factory=set)
    tier2_hosts: set[str] = field(default_factory=set)
    tier2_urls: set[str] = field(default_factory=set)

    def tier(self, url: str) -> int:
        normalized = url.rstrip("/")
        if normalized in self.tier1_urls:
            return 1
        if normalized in self.tier2_urls:
            return 2
        host = urlsplit(url).netloc.lower().removeprefix("www.")
        if host in self.tier2_hosts:
            return 2
        return 3

    def including(
        self,
        indicators: Mapping[str, Mapping[str, Any]],
        document_url: str | None = None,
    ) -> TierRegistry:
        """Copy that also trusts the sources of the task's collector summaries.

        ``input/indicators.json`` is written by the collectors from the
        registry (never by the model; the brain may write only ``output/``),
        so its ``source_url``/``source_page`` are registry-derived tier 1. The
        same holds for ``input/document.json`` written by a tier-2 watcher.
        """
        urls = set(self.tier1_urls)
        for ind in indicators.values():
            for key in ("source_url", "source_page"):
                if ind.get(key):
                    urls.add(str(ind[key]).rstrip("/"))
        docs = set(self.tier2_urls) | ({document_url.rstrip("/")} if document_url else set())
        return TierRegistry(tier1_urls=urls, tier2_hosts=set(self.tier2_hosts), tier2_urls=docs)

    @classmethod
    def load(cls, root: Path) -> TierRegistry:
        """Build from every ``ministries/*/indicators.yaml`` + ``watchers.yaml``."""
        reg = cls()
        for path in sorted((root / "ministries").glob("*/indicators.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for entry in raw.get("indicators", []):
                src = entry.get("source", {})
                for key in ("url", "page"):
                    if src.get(key):
                        reg.tier1_urls.add(str(src[key]).rstrip("/"))
        watchers = root / "watchers.yaml"
        if watchers.is_file():
            raw = yaml.safe_load(watchers.read_text(encoding="utf-8")) or {}
            for w in raw.get("watchers", []):
                reg.tier2_hosts.add(urlsplit(str(w["url"])).netloc.lower().removeprefix("www."))
        return reg


def validate_evidence(
    front: Mapping[str, Any],
    body: str,
    indicators: Mapping[str, Mapping[str, Any]],
    tiers: TierRegistry,
) -> list[str]:
    """Raise :class:`EvidenceError` unless the report obeys чл. 8.

    Returns the referenced indicator ids (for the review/reconciliation).
    """
    prose = "\n".join([str(front.get("title", "")), str(front.get("summary", "")), body])
    bare = check_bare_numbers(prose)
    if bare:
        raise EvidenceError(f"число без референция към индикатор от ниво 1: {', '.join(bare[:5])}")
    refs = indicator_refs(prose)
    unknown = sorted({i for i, _ in refs if i not in indicators})
    if unknown:
        raise EvidenceError(f"референция към индикатор извън входа: {', '.join(unknown)}")
    for source in _urls(front.get("sources", [])):
        if tiers.tier(source) == 3:
            raise EvidenceError(f"източник от ниво 3 (медия/непознат) цитиран като факт: {source}")
    return sorted({i for i, _ in refs})


def render_refs(text: str, indicators: Mapping[str, Mapping[str, Any]]) -> str:
    """Replace every reference with the collector's number, Bulgarian format."""

    def sub(m: re.Match[str]) -> str:
        ind = indicators[m[1]]
        fld = m[2] or "value"
        val = ind.get(fld)
        if val is None:
            return "н.д."
        if fld in ("period", "previous_period"):
            return str(val)
        unit = "%" if fld == "change_pct" else (" " + str(ind.get("unit", ""))).rstrip()
        sign = "+" if fld in ("change", "change_pct", "yoy_change") and float(val) > 0 else ""
        return f"{sign}{format_bg(float(val))}{unit if fld != 'change_pct' else '%'}"

    return REF.sub(sub, text)


def format_bg(value: float) -> str:
    """1234.5 -> '1 234,5' (Bulgarian grouping, up to 2 decimals)."""
    text = f"{value:,.2f}".rstrip("0").rstrip(".")
    return text.replace(",", " ").replace(".", ",")


def _urls(items: Iterable[Any]) -> list[str]:
    return [str(i["url"]) if isinstance(i, Mapping) else str(getattr(i, "url", i)) for i in items]
