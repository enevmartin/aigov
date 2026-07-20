"""Validate ``done/`` tasks and copy their artifacts into ``published/``.

Layout produced::

    published/{ministry}/{date}/report.md
    published/{ministry}/{date}/aggregates.json
    published/{ministry}/{date}/news.json        # news_digest tasks only
    published/index.json                          # regenerated every publish

The site reads exactly these files and nothing else (invariant #2).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import frontmatter
import yaml
from pydantic import BaseModel

from core.archive import ingest_aggregates, rebuild_timeseries
from core.config import AppConfig
from core.contracts import (
    OPTIONAL_ARTIFACTS,
    REPORT_MODEL,
    REQUIRED_ARTIFACTS,
    Aggregates,
    CorrectionReport,
    NewsDigest,
    Report,
    SignalStats,
    TaskSpec,
)
from core.queue import FileQueue, QueueState

INDEX_FILE = "index.json"

_JSON_MODELS: dict[str, type[BaseModel]] = {
    "aggregates.json": Aggregates,
    "news.json": NewsDigest,
    "signals.json": SignalStats,
}


class OutputRejected(Exception):
    """Brain output failed validation; the reason becomes ``reason.txt``."""


def _stamp_review(report_path: Path, approval: dict[str, object]) -> None:
    """Write ``reviewed: true, reviewer: <агент>`` into the front-matter.

    Stamped by the CORE after an approved second reading — a brain writing
    these fields itself is overwritten here, so the stamp is trustworthy.
    """
    if not report_path.is_file() or not approval:
        return
    post = frontmatter.loads(report_path.read_text(encoding="utf-8"))
    post.metadata["reviewed"] = True
    post.metadata["reviewer"] = approval.get("reviewer", "unknown")
    report_path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")


def _validate_report(path: Path, model: type[Report]) -> Report:
    try:
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
        report = model.model_validate(post.metadata)
    except Exception as exc:
        raise OutputRejected(f"report.md front-matter invalid: {exc}") from exc
    if not post.content.strip():
        raise OutputRejected("report.md has no body")
    return report


def _validate_json(path: Path, model: type[BaseModel]) -> BaseModel:
    try:
        return model.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:
        raise OutputRejected(f"{path.name} invalid: {exc}") from exc


def validate_output(output_dir: Path, spec: TaskSpec) -> dict[str, BaseModel]:
    """Validate a task's artifacts per its type; return the validated models.

    Required artifacts (``REQUIRED_ARTIFACTS[spec.type]``) must exist and
    validate; optional ones validate when present. Every artifact carrying a
    ``ministry`` field must match the task's ministry — a brain must not
    publish on behalf of another ministry. Raises :class:`OutputRejected`
    with a human-readable reason on any violation.
    """
    validated: dict[str, BaseModel] = {}
    required = REQUIRED_ARTIFACTS[spec.type]
    optional = OPTIONAL_ARTIFACTS[spec.type]

    for name in required:
        if not (output_dir / name).is_file():
            raise OutputRejected(f"{spec.type.value} task produced no {name}")
    for name in (*required, *optional):
        path = output_dir / name
        if not path.is_file():
            continue
        if name == "report.md":
            validated[name] = _validate_report(path, REPORT_MODEL[spec.type])
        else:
            validated[name] = _validate_json(path, _JSON_MODELS[name])

    for name, model_obj in validated.items():
        artifact_ministry = getattr(model_obj, "ministry", None)
        if artifact_ministry is not None and artifact_ministry != spec.ministry:
            raise OutputRejected(
                f"{name} claims ministry {artifact_ministry!r} but task is {spec.ministry!r}"
            )
    return validated


def publish_all(config: AppConfig) -> dict[str, list[str]]:
    """Publish every APPROVED task in ``done/``; reject invalid ones.

    Second reading is mandatory: tasks in ``done/`` without an approve
    marker are skipped (they are awaiting review, or their review is still
    queued) and reported under ``"unreviewed"``. A published task directory
    is deleted from the queue (its artifacts now live in ``published/``).
    Returns ``{"published": [...], "rejected": [...], "unreviewed": [...]}``.
    """
    from core.review import approval_info, is_approved  # one-way dep: publish -> review

    queue = FileQueue(config.path("tasks"))
    published_root = config.path("published")
    results: dict[str, list[str]] = {"published": [], "rejected": [], "unreviewed": []}

    for task_id in queue.list_tasks(QueueState.DONE):
        spec = queue.load_spec(QueueState.DONE, task_id)
        task_dir = queue.path(QueueState.DONE, task_id)
        if not is_approved(task_dir):
            results["unreviewed"].append(task_id)
            continue
        _stamp_review(task_dir / "output" / "report.md", approval_info(task_dir))
        try:
            validated = validate_output(task_dir / "output", spec)
            report = validated.get("report.md")
            if isinstance(report, CorrectionReport) and not _original_dir(
                published_root, report
            ).is_dir():
                raise OutputRejected(
                    f"correction references unknown publication "
                    f"{report.corrects.ministry}/{report.corrects.date}"
                )
        except OutputRejected as exc:
            queue.fail(task_id, str(exc), source_state=QueueState.DONE)
            results["rejected"].append(task_id)
            continue

        # every artifact model carries the publication date; the type subdir
        # keeps same-day publications of one ministry from clobbering each other
        dates = {m.date for m in validated.values() if hasattr(m, "date")}
        day = sorted(dates)[-1].isoformat()
        target = published_root / spec.ministry / day / spec.type.value
        target.mkdir(parents=True, exist_ok=True)
        for name in validated:
            shutil.copy2(task_dir / "output" / name, target / name)

        # institutional memory: archive the numbers, refresh the public series
        aggregates = validated.get("aggregates.json")
        if isinstance(aggregates, Aggregates):
            db_path = config.root / "data" / "archive.duckdb"
            ingest_aggregates(db_path, aggregates)
            rebuild_timeseries(db_path, published_root, spec.ministry)

        # corrections: the original is NEVER edited — it gains a sidecar
        if isinstance(report, CorrectionReport):
            _link_correction(published_root, report, day)

        shutil.rmtree(task_dir)
        results["published"].append(task_id)

    if results["published"]:
        rebuild_index(published_root, ministry_names(config), cabinet_roster(config))
    return results


CORRECTED_BY_FILE = "corrected_by.json"


def _original_dir(published_root: Path, correction: CorrectionReport) -> Path:
    """The directory of the publication a correction references.

    With a known type the sidecar sits next to that publication; without
    one it attaches at the date level (badge covers the whole day).
    """
    base = published_root / correction.corrects.ministry / (
        correction.corrects.date.isoformat()
    )
    if correction.corrects.type:
        return base / correction.corrects.type
    return base


def _link_correction(published_root: Path, correction: CorrectionReport, day: str) -> None:
    """Attach a ``corrected_by.json`` sidecar to the ORIGINAL publication.

    The original artifacts stay byte-identical (history is inviolable);
    only this new metadata file appears next to them.
    """
    original_dir = _original_dir(published_root, correction)
    sidecar = original_dir / CORRECTED_BY_FILE
    payload: dict[str, list[dict[str, str]]] = {"corrections": []}
    if sidecar.is_file():
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    entry = {
        "ministry": correction.ministry,
        "date": day,
        "title": correction.title,
        "summary": correction.summary,
    }
    payload["corrections"] = [
        c for c in payload["corrections"] if c.get("date") != day
    ] + [entry]
    sidecar.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def ministry_names(config: AppConfig) -> dict[str, str]:
    """Map ministry slug -> display name from the declarations.

    The site reads ONLY published/ (invariant #2), so display names must
    travel inside index.json; the core reads the declarations on its behalf.
    """
    return {str(entry["slug"]): str(entry["name"]) for entry in cabinet_roster(config)}


def cabinet_roster(config: AppConfig) -> list[dict[str, object]]:
    """The full cabinet for the site: every declared ministry, active or not.

    The site may read only published/, but the Кабинет page must show
    ministers that have not published yet ("подготвя се") — so the roster
    travels inside index.json, written by the core from the declarations.
    """
    roster: list[dict[str, object]] = []
    for entry in config.ministries:
        declaration_path = config.ministry_dir(entry.slug) / "ministry.yaml"
        if not declaration_path.is_file():
            continue
        declaration = yaml.safe_load(declaration_path.read_text(encoding="utf-8"))
        persona = declaration.get("minister_persona", {})
        roster.append(
            {
                "slug": entry.slug,
                "name": str(declaration.get("name", entry.slug)),
                "persona": str(persona.get("име", "")),
                "persona_style": str(persona.get("стил", "")),
                "enabled": entry.enabled,
            }
        )
    return roster


def rebuild_index(
    published_root: Path,
    names: dict[str, str] | None = None,
    cabinet: list[dict[str, object]] | None = None,
) -> Path:
    """Regenerate ``published/index.json`` from the directory tree.

    The site uses this as its table of contents: per ministry, the sorted
    list of publication dates, which artifacts each date has, the ministry
    display names, and the full cabinet roster (incl. not-yet-active
    ministries for the "подготвя се" cards).
    """
    index: dict[str, list[dict[str, object]]] = {}
    if published_root.is_dir():
        for ministry_dir in sorted(p for p in published_root.iterdir() if p.is_dir()):
            entries: list[dict[str, object]] = []
            for date_dir in sorted(p for p in ministry_dir.iterdir() if p.is_dir()):
                types: dict[str, list[str]] = {}
                for type_dir in sorted(p for p in date_dir.iterdir() if p.is_dir()):
                    artifacts = sorted(
                        p.name for p in type_dir.iterdir() if p.is_file()
                    )
                    if artifacts:
                        types[type_dir.name] = artifacts
                if types:
                    entries.append({"date": date_dir.name, "types": types})
            if entries:
                index[ministry_dir.name] = entries

    published_root.mkdir(parents=True, exist_ok=True)
    target = published_root / INDEX_FILE
    payload = {
        "ministries": index,
        "names": {slug: (names or {}).get(slug, slug) for slug in index},
        "cabinet": cabinet or [],
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target
