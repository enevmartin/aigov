"""Watch official tier-2 feeds and turn relevant documents into tasks."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import feedparser
import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from core.contracts import TaskSpec, TaskType
from core.queue import FileQueue

MAX_TEXT_CHARS = 60_000  # a minister reads the act, not the whole gazette
Fetch = Callable[[str], bytes]


class WatcherVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verified_at: date
    http_status: int | None
    robots: str
    items: int | None = None
    note: str | None = None


class WatcherSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_.-]+$")
    name: str
    publisher: str
    kind: str = Field(description="законопроект, закон, брой на ДВ, обсъждане ...")
    url: HttpUrl = Field(description="the RSS/Atom feed")
    # SPA sites (parliament.bg) serve no text in HTML: read the document from
    # the site's own JSON API instead — {id} is taken from the item link
    document_api: str | None = None
    id_pattern: str | None = None
    # field-name fragments removed from API documents before any model sees
    # them (чл. 5: e.g. the names of the MPs who tabled a bill)
    redact: list[str] = Field(default_factory=list)
    enabled: bool = True
    disabled_reason: str | None = None
    verification: WatcherVerification | None = None

    @model_validator(mode="after")
    def _enabled_needs_live_check(self) -> WatcherSpec:
        if not self.enabled and not self.disabled_reason:
            raise ValueError(f"{self.id}: enabled: false requires disabled_reason")
        if self.enabled:
            v = self.verification
            if v is None or v.http_status != 200 or v.robots != "allowed":
                raise ValueError(f"{self.id}: an enabled watcher needs a passing live check")
        return self


class WatcherRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    watchers: list[WatcherSpec]
    # ministry slug -> title keywords (lowercase stems) that route a document
    routing: dict[str, list[str]]

    def enabled(self) -> list[WatcherSpec]:
        return [w for w in self.watchers if w.enabled]


@dataclass(frozen=True)
class Document:
    url: str
    title: str
    publisher: str
    kind: str
    watcher: str
    api_url: str | None = None  # where the text is read from (else: url)
    redact: tuple[str, ...] = ()


def load_watchers(root: Path) -> WatcherRegistry:
    raw = yaml.safe_load((root / "watchers.yaml").read_text(encoding="utf-8"))
    return WatcherRegistry.model_validate(raw)


def parse_feed(payload: bytes, base_url: str) -> list[tuple[str, str]]:
    """``(absolute_link, title)`` pairs of a feed (RSS 2.0 / Atom)."""
    feed = feedparser.parse(payload)
    out = []
    for entry in feed.entries:
        link, title = str(entry.get("link", "")).strip(), str(entry.get("title", "")).strip()
        if link and title:
            out.append((urljoin(base_url, link), title))
    return out


def route(title: str, routing: dict[str, list[str]]) -> list[str]:
    """Ministries whose keywords occur in *title* (case-insensitive stems)."""
    lowered = title.lower()
    return sorted(slug for slug, words in routing.items() if any(w in lowered for w in words))


def scan(
    registry: WatcherRegistry, fetch: Fetch, seen: set[str]
) -> list[tuple[Document, list[str]]]:
    """New, routed documents from every enabled watcher (marks them seen)."""
    found = []
    for watcher in registry.enabled():
        url = str(watcher.url)
        for link, title in parse_feed(fetch(url), url):
            if link in seen:
                continue
            seen.add(link)
            slugs = route(title, registry.routing)
            if slugs:
                doc = Document(
                    link,
                    title,
                    watcher.publisher,
                    watcher.kind,
                    watcher.id,
                    api_url=_api_url(watcher, link),
                    redact=tuple(watcher.redact),
                )
                found.append((doc, slugs))
    return found


def _api_url(watcher: WatcherSpec, link: str) -> str | None:
    if not (watcher.document_api and watcher.id_pattern):
        return None
    m = re.search(watcher.id_pattern, link)
    return watcher.document_api.format(id=m.group(1)) if m else None


def json_to_text(payload: bytes, redact: Iterable[str] = ()) -> str:
    """Readable ``key: value`` lines of a JSON document (non-empty scalars).

    Any key containing one of *redact* is dropped with its whole subtree.
    """
    lines: list[str] = []
    drop = tuple(redact)

    def walk(node: Any, prefix: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if any(d in str(k) for d in drop):
                    continue
                walk(v, f"{prefix}{k}.")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{prefix}{i}.")
        elif node not in (None, "", "0000-00-00"):
            lines.append(f"{prefix.rstrip('.')}: {node}")

    walk(json.loads(payload), "")
    return "\n".join(lines)[:MAX_TEXT_CHARS]


def html_to_text(payload: bytes) -> str:
    """Plain text of an official page (scripts/styles/markup dropped)."""
    text = payload.decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()[:MAX_TEXT_CHARS]


def fetch_document(doc: Document, fetch: Fetch, today: date) -> dict[str, Any]:
    """The task's ``document.json``: metadata + text + sha256 of the payload."""
    payload = fetch(doc.api_url or doc.url)
    text = json_to_text(payload, doc.redact) if doc.api_url else html_to_text(payload)
    return {
        "url": doc.url,
        "title": doc.title,
        "publisher": doc.publisher,
        "kind": doc.kind,
        "retrieved": today.isoformat(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "text": text,
    }


def enqueue_event_analysis(
    queue: FileQueue,
    ministry: str,
    document: dict[str, Any],
    indicators: Iterable[dict[str, Any]],
    trigger: list[dict[str, Any]] | None = None,
) -> str | None:
    """One ``event_analysis`` task: the document + the ministry's tier-1 numbers.

    Returns the task id, or ``None`` if the ministry has no collected
    indicators (no tier-1 context -> no analysis, чл. 8) or it was enqueued.
    """
    summaries = list(indicators)
    if not summaries:
        return None
    now = datetime.now(tz=UTC)
    digest = str(document["sha256"])[:10]
    spec = TaskSpec(
        id=f"{ministry}-{now:%Y-%m-%d}-event-{digest}",
        ministry=ministry,
        type=TaskType.EVENT_ANALYSIS,
        created=now,
    )
    files = {
        "document.json": json.dumps(document, ensure_ascii=False, indent=2).encode(),
        "indicators.json": json.dumps(summaries, ensure_ascii=False, indent=2).encode(),
    }
    if trigger:
        files["trigger.json"] = json.dumps(trigger, ensure_ascii=False, indent=2).encode()
    try:
        queue.enqueue(spec, input_files=files)
    except FileExistsError:
        return None  # the same document for the same ministry today
    return spec.id


def verify_watchers_file(
    path: Path, fetch_response: Callable[[str], Any], allowed: Callable[[str], bool], today: date
) -> WatcherRegistry:
    """LIVE check of every declared watcher; failures are disabled with the reason."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    for entry in raw["watchers"]:
        url = str(entry["url"])
        check: dict[str, Any] = {"verified_at": today.isoformat()}
        problem = None
        if not allowed(url):
            check.update(http_status=None, robots="disallowed")
            problem = "robots.txt забранява пътя"
        else:
            try:
                response = fetch_response(url)
                items = parse_feed(response.content, url)
                check.update(http_status=response.status_code, robots="allowed", items=len(items))
                if not items:
                    problem = "няма машинно четим поток (RSS/Atom без записи)"
            except Exception as exc:  # noqa: BLE001 — record, disable, carry on
                status = getattr(getattr(exc, "response", None), "status_code", None)
                check.update(http_status=status, robots="allowed")
                problem = f"HTTP {status}" if status else f"{type(exc).__name__}"
        entry["verification"] = check
        if problem:
            check["note"] = problem
            entry["enabled"] = False
            entry["disabled_reason"] = f"проверка на живо {today.isoformat()}: {problem}"
    registry = WatcherRegistry.model_validate(raw)
    path.write_text(
        "# Tier-2 official-document watchers (чл. 8). `verification` is written by\n"
        "# `aigov-data watch-verify` from a LIVE check — do not edit it by hand.\n"
        + yaml.safe_dump(raw, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    return registry
