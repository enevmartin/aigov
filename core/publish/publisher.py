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

from core.config import AppConfig
from core.contracts import Aggregates, NewsDigest, Report, TaskSpec, TaskType
from core.queue import FileQueue, QueueState

INDEX_FILE = "index.json"


class OutputRejected(Exception):
    """Brain output failed validation; the reason becomes ``reason.txt``."""


def validate_output(
    output_dir: Path, spec: TaskSpec
) -> tuple[Report, Aggregates, NewsDigest | None]:
    """Validate the three artifacts against the contract.

    Raises :class:`OutputRejected` with a human-readable reason on any
    violation — including a report whose front-matter ministry does not match
    the task's ministry (a brain must not publish on behalf of another
    ministry).
    """
    report_path = output_dir / "report.md"
    aggregates_path = output_dir / "aggregates.json"
    news_path = output_dir / "news.json"

    if not report_path.is_file():
        raise OutputRejected("missing report.md")
    if not aggregates_path.is_file():
        raise OutputRejected("missing aggregates.json")

    try:
        post = frontmatter.loads(report_path.read_text(encoding="utf-8"))
        report = Report.model_validate(post.metadata)
    except Exception as exc:
        raise OutputRejected(f"report.md front-matter invalid: {exc}") from exc
    if not post.content.strip():
        raise OutputRejected("report.md has no body")

    try:
        aggregates = Aggregates.model_validate(
            json.loads(aggregates_path.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        raise OutputRejected(f"aggregates.json invalid: {exc}") from exc

    news: NewsDigest | None = None
    if spec.type is TaskType.NEWS_DIGEST:
        if not news_path.is_file():
            raise OutputRejected("news_digest task produced no news.json")
        try:
            news = NewsDigest.model_validate(json.loads(news_path.read_text(encoding="utf-8")))
        except Exception as exc:
            raise OutputRejected(f"news.json invalid: {exc}") from exc

    for name, artifact_ministry in (
        ("report.md", report.ministry),
        ("aggregates.json", aggregates.ministry),
        *((("news.json", news.ministry),) if news else ()),
    ):
        if artifact_ministry != spec.ministry:
            raise OutputRejected(
                f"{name} claims ministry {artifact_ministry!r} but task is {spec.ministry!r}"
            )
    return report, aggregates, news


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
            report, _aggregates, news = validate_output(task_dir / "output", spec)
        except OutputRejected as exc:
            queue.fail(task_id, str(exc), source_state=QueueState.DONE)
            results["rejected"].append(task_id)
            continue

        target = published_root / spec.ministry / report.date.isoformat()
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(task_dir / "output" / "report.md", target / "report.md")
        shutil.copy2(task_dir / "output" / "aggregates.json", target / "aggregates.json")
        if news is not None:
            shutil.copy2(task_dir / "output" / "news.json", target / "news.json")

        shutil.rmtree(task_dir)
        results["published"].append(task_id)

    if results["published"]:
        rebuild_index(published_root)
    return results


def rebuild_index(published_root: Path) -> Path:
    """Regenerate ``published/index.json`` from the directory tree.

    The site uses this as its table of contents: per ministry, the sorted
    list of publication dates and which artifacts each date has.
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
    target.write_text(
        json.dumps({"ministries": index}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target
