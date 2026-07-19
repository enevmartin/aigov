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

from core.config import AppConfig
from core.contracts import (
    OPTIONAL_ARTIFACTS,
    REPORT_MODEL,
    REQUIRED_ARTIFACTS,
    Aggregates,
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
    """Publish every task in ``done/``; reject invalid ones to ``failed/``.

    A published task directory is deleted from the queue (its artifacts now
    live in ``published/``; the queue is working state, not an archive).
    Returns ``{"published": [...ids], "rejected": [...ids]}``.
    """
    queue = FileQueue(config.path("tasks"))
    published_root = config.path("published")
    results: dict[str, list[str]] = {"published": [], "rejected": []}

    for task_id in queue.list_tasks(QueueState.DONE):
        spec = queue.load_spec(QueueState.DONE, task_id)
        task_dir = queue.path(QueueState.DONE, task_id)
        try:
            validated = validate_output(task_dir / "output", spec)
        except OutputRejected as exc:
            queue.fail(task_id, str(exc), source_state=QueueState.DONE)
            results["rejected"].append(task_id)
            continue

        # every artifact model carries the publication date
        dates = {m.date for m in validated.values() if hasattr(m, "date")}
        day = sorted(dates)[-1].isoformat()
        target = published_root / spec.ministry / day
        target.mkdir(parents=True, exist_ok=True)
        for name in validated:
            shutil.copy2(task_dir / "output" / name, target / name)

        shutil.rmtree(task_dir)
        results["published"].append(task_id)

    if results["published"]:
        rebuild_index(published_root, ministry_names(config))
    return results


def ministry_names(config: AppConfig) -> dict[str, str]:
    """Map ministry slug -> display name from the declarations.

    The site reads ONLY published/ (invariant #2), so display names must
    travel inside index.json; the core reads the declarations on its behalf.
    """
    names: dict[str, str] = {}
    for entry in config.ministries:
        declaration_path = config.ministry_dir(entry.slug) / "ministry.yaml"
        if declaration_path.is_file():
            declaration = yaml.safe_load(declaration_path.read_text(encoding="utf-8"))
            names[entry.slug] = str(declaration.get("name", entry.slug))
    return names


def rebuild_index(published_root: Path, names: dict[str, str] | None = None) -> Path:
    """Regenerate ``published/index.json`` from the directory tree.

    The site uses this as its table of contents: per ministry, the sorted
    list of publication dates, which artifacts each date has, and the
    ministry display names.
    """
    index: dict[str, list[dict[str, object]]] = {}
    if published_root.is_dir():
        for ministry_dir in sorted(p for p in published_root.iterdir() if p.is_dir()):
            entries: list[dict[str, object]] = []
            for date_dir in sorted(p for p in ministry_dir.iterdir() if p.is_dir()):
                artifacts = sorted(p.name for p in date_dir.iterdir() if p.is_file())
                if artifacts:
                    entries.append({"date": date_dir.name, "artifacts": artifacts})
            if entries:
                index[ministry_dir.name] = entries

    published_root.mkdir(parents=True, exist_ok=True)
    target = published_root / INDEX_FILE
    payload = {
        "ministries": index,
        "names": {slug: (names or {}).get(slug, slug) for slug in index},
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target
