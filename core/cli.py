"""aigov CLI: ``ingest | enqueue | session | publish | status``.

This module is the composition root. The ``session`` command resolves the
configured brain by importing ``brains.{config.brain}`` **by name from
config.yaml** — the only place core code touches the brains package, with
zero knowledge of any concrete adapter (swapping brains remains a one-line
config change).
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import polars as pl
import yaml

from core.config import AppConfig, load_config
from core.contracts import TaskSpec, TaskType, export_json_schemas
from core.ingest import collect_rss, detect_spike
from core.publish import publish_all
from core.publish.health import record_session, record_source_result
from core.queue import FileQueue, QueueState
from core.session import TaskRunner, run_session


def _load_ministry(config: AppConfig, slug: str) -> dict[str, Any]:
    """Read ``ministries/{slug}/ministry.yaml`` (declarations only)."""
    path = config.ministry_dir(slug) / "ministry.yaml"
    return cast("dict[str, Any]", yaml.safe_load(path.read_text(encoding="utf-8")))


def _maybe_enqueue_crisis(config: AppConfig, slug: str, staged: Path) -> None:
    """Deterministic spike check over freshly staged news; enqueue on trigger.

    Detection is pure Python (чл. 7): the LLM sees the task only after the
    core decided there is a spike. One crisis task per ministry per day —
    a second trigger the same day is silently skipped.
    """
    declaration = _load_ministry(config, slug)
    crisis_cfg = declaration.get("crisis_keywords") or {}
    keywords: list[str] = crisis_cfg.get("keywords", [])
    if not keywords:
        return

    frame = pl.read_parquet(staged)
    texts = [
        f"{title} {summary}"
        for title, summary in zip(frame["title"], frame["summary"], strict=True)
    ]
    trigger = detect_spike(texts, keywords, int(crisis_cfg.get("min_hits", 3)))
    if trigger is None:
        return

    now = datetime.now(tz=UTC)
    spec = TaskSpec(
        id=f"{slug}-{now.strftime('%Y-%m-%d')}-crisis-brief",
        ministry=slug,
        type=TaskType.CRISIS_BRIEF,
        created=now,
    )
    trigger_json = json.dumps(
        {"keywords": trigger.keywords, "counts": trigger.counts},
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    queue = FileQueue(config.path("tasks"))
    try:
        # input is a COPY of the staged news (the daily digest still needs it)
        queue.enqueue(
            spec,
            input_files={f"staging/{staged.name}": staged.read_bytes(),
                         "trigger.json": trigger_json},
        )
    except FileExistsError:
        return  # already triggered today
    print(f"[{slug}] CRISIS trigger {trigger.counts} -> enqueued {spec.id}")


def cmd_ingest(config: AppConfig, ministry: str | None) -> int:
    """Collect RSS for one or all ENABLED ministries into staging.

    Every source attempt is recorded in the health ledger (3 consecutive
    failures -> degraded + data_quality_alert); a keyword spike in the fresh
    items auto-enqueues a crisis_brief task.
    """
    slugs = [ministry] if ministry else [m.slug for m in config.enabled_ministries()]
    staged_any = False
    for slug in slugs:
        declaration = _load_ministry(config, slug)
        rss_sources = declaration.get("sources", {}).get("rss", [])
        if not rss_sources:
            print(f"[{slug}] no RSS sources declared, skipping")
            continue
        result = collect_rss(rss_sources, config.path("data_staging"), slug)
        for source in result.sources:
            record_source_result(
                config, slug, source.name, source.url, ok=source.ok, note=source.note
            )
        if result.staged is None:
            print(f"[{slug}] nothing collected")
        else:
            print(f"[{slug}] staged {result.staged.relative_to(config.root)} "
                  f"({result.items} items)")
            staged_any = True
            _maybe_enqueue_crisis(config, slug, result.staged)
    return 0 if staged_any or not slugs else 1


def _staged_input(config: AppConfig, ministry: str) -> tuple[dict[str, bytes], list[Path]]:
    """Input from data/staging (analysis, news_digest, manual crisis_brief)."""
    staging = config.path("data_staging") / ministry
    staged_files = sorted(staging.glob("*.parquet")) if staging.is_dir() else []
    files = {f"staging/{p.name}": p.read_bytes() for p in staged_files}
    return files, staged_files


def _published_input(
    config: AppConfig, slugs: list[str], days: int | None = None
) -> dict[str, bytes]:
    """Input from already-published artifacts (weekly_report, joint_report)."""
    published = config.path("published")
    files: dict[str, bytes] = {}
    for slug in slugs:
        ministry_dir = published / slug
        if not ministry_dir.is_dir():
            continue
        dates = sorted((p for p in ministry_dir.iterdir() if p.is_dir()), key=lambda p: p.name)
        for date_dir in dates[-days:] if days else dates[-1:]:
            for artifact in sorted(date_dir.iterdir()):
                if artifact.is_file():
                    key = f"published/{slug}/{date_dir.name}/{artifact.name}"
                    files[key] = artifact.read_bytes()
    return files


def cmd_enqueue(config: AppConfig, ministry: str, task_type: str) -> int:
    """Create a pending task with type-appropriate input.

    - analysis / news_digest / crisis_brief: staged parquet from ingest
    - weekly_report: the ministry's own published artifacts (last 7 days)
    - joint_report: latest published artifacts of ALL enabled ministries
      (needs 2+ with publications) — the "prime minister" composes only
      from what is already public
    - signal_triage: phase 3, schema-only for now
    """
    t = TaskType(task_type)
    consumed: list[Path] = []

    if t is TaskType.SIGNAL_TRIAGE:
        print("signal_triage is phase 3: schema and tests exist, intake does not yet")
        return 1
    if t is TaskType.JOINT_REPORT:
        contributors = [
            m.slug for m in config.enabled_ministries() if m.slug != ministry
        ]
        input_files = _published_input(config, contributors)
        published_slugs = {key.split("/")[1] for key in input_files}
        if len(published_slugs) < 2:
            print(
                f"[{ministry}] joint_report needs published reports from 2+ "
                f"ministries (found {len(published_slugs)})"
            )
            return 1
    elif t is TaskType.WEEKLY_REPORT:
        input_files = _published_input(config, [ministry], days=7)
        if not input_files:
            print(f"[{ministry}] weekly_report needs published days — nothing found")
            return 1
    else:
        input_files, consumed = _staged_input(config, ministry)
        if not input_files:
            print(f"[{ministry}] no staged data — run 'aigov ingest' first")
            return 1

    now = datetime.now(tz=UTC)
    spec = TaskSpec(
        id=f"{ministry}-{now.strftime('%Y-%m-%d-%H%M%S')}-{task_type.replace('_', '-')}",
        ministry=ministry,
        type=t,
        created=now,
    )
    schemas_dir = config.path("data_staging") / "_schemas"
    export_json_schemas(schemas_dir)

    queue = FileQueue(config.path("tasks"))
    queue.enqueue(
        spec,
        input_files=input_files,
        expected_schema=(schemas_dir / "aggregates.schema.json").read_text(encoding="utf-8"),
    )
    for p in consumed:  # staging is ephemeral: data now lives in the task
        p.unlink()
    print(f"enqueued {spec.id} with {len(input_files)} input file(s)")
    return 0


def _brain_resolver(config: AppConfig, dry_run: bool) -> Callable[[str], TaskRunner]:
    """Composition root: map a brain name to a concrete adapter.

    This closure is the ONLY place that touches the brains package, and it
    does so purely by the name configured in config.yaml. With ``dry_run``
    every name resolves to the deterministic fake brain (zero tokens).
    """
    cache: dict[str, TaskRunner] = {}

    def resolve(name: str) -> TaskRunner:
        if dry_run:
            from tests.fake_brain import FakeBrain  # dev dependency, lazily

            return FakeBrain()
        if name not in cache:
            module = importlib.import_module(f"brains.{name}")
            cache[name] = module.get_brain(config)
        return cache[name]

    return resolve


def cmd_session(config: AppConfig, dry_run: bool) -> int:
    """Run one cabinet session, resolving the brain PER TASK.

    Each task uses its ministry's brain override when set, else the global
    ``brain`` — two ministries can run on different brains in one session.
    """
    results = run_session(config, _brain_resolver(config, dry_run))
    record_session(config, results)
    for task_id in results["resumed"]:
        print(f"resumed {task_id} (reclaimed from a dead session)")
    for task_id in results["done"]:
        print(f"done   {task_id}")
    for task_id in results["approved"]:
        print(f"approved {task_id} (second reading passed)")
    for task_id in results["revised"]:
        print(f"revise  {task_id} (sent back with review notes)")
    for task_id in results["retried"]:
        print(f"retry  {task_id} (will run again next session)")
    for task_id in results["failed"]:
        print(f"FAILED {task_id}")
    return 0 if not results["failed"] else 1


def cmd_export(config: AppConfig, ministry: str, brain: str) -> int:
    """Export a ministry as the framework-specific artifact of *brain*."""
    exporter = importlib.import_module(f"brains.{brain}.exporter")
    written: list[Path] = exporter.export_ministry(config, ministry)
    for path in written:
        print(f"exported {path.relative_to(config.root)}")
    return 0


def cmd_publish(config: AppConfig) -> int:
    """Validate done tasks and release them to published/."""
    results = publish_all(config)
    for task_id in results["published"]:
        print(f"published {task_id}")
    for task_id in results["unreviewed"]:
        print(f"awaiting review: {task_id} (will publish after approval)")
    for task_id in results["rejected"]:
        print(f"REJECTED  {task_id} (see tasks/failed/{task_id}/reason.txt)")
    return 0 if not results["rejected"] else 1


def cmd_status(config: AppConfig) -> int:
    """Print queue counts and the published table of contents."""
    queue = FileQueue(config.path("tasks"))
    for state in QueueState.ALL:
        tasks = queue.list_tasks(state)
        listing = f" — {', '.join(tasks)}" if tasks else ""
        print(f"{state:8} {len(tasks)}{listing}")

    published = config.path("published")
    ministries = (
        sorted(p.name for p in published.iterdir() if p.is_dir()) if published.is_dir() else []
    )
    for slug in ministries:
        dates = sorted(p.name for p in (published / slug).iterdir() if p.is_dir())
        latest = dates[-1] if dates else "—"
        print(f"published/{slug}: {len(dates)} day(s), latest {latest}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point (``aigov`` script)."""
    parser = argparse.ArgumentParser(prog="aigov", description="aigov.bg pipeline operations")
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="repo root (default: current dir)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="collect RSS/data into staging")
    p_ingest.add_argument("--ministry", help="one ministry slug (default: all)")

    p_enqueue = sub.add_parser("enqueue", help="turn staged data into a pending task")
    p_enqueue.add_argument("--ministry", required=True)
    p_enqueue.add_argument(
        "--type",
        default=TaskType.NEWS_DIGEST.value,
        # review tasks are created automatically by the session, never enqueued by hand
        choices=[t.value for t in TaskType if t is not TaskType.REVIEW],
        dest="task_type",
    )

    p_session = sub.add_parser("session", help="run a cabinet session (configured brain)")
    p_session.add_argument(
        "--dry-run", action="store_true", help="use the deterministic fake brain (no tokens)"
    )

    sub.add_parser("publish", help="validate done tasks and release to published/")
    sub.add_parser("status", help="queue and published overview")

    p_export = sub.add_parser(
        "export", help="export a ministry as a framework-specific agent artifact"
    )
    p_export.add_argument("--ministry", required=True)
    p_export.add_argument("--brain", required=True, help="claude_code | openclaw | api")

    args = parser.parse_args(argv)
    config = load_config(args.root.resolve())

    if args.command == "ingest":
        return cmd_ingest(config, args.ministry)
    if args.command == "enqueue":
        return cmd_enqueue(config, args.ministry, args.task_type)
    if args.command == "session":
        return cmd_session(config, args.dry_run)
    if args.command == "publish":
        return cmd_publish(config)
    if args.command == "export":
        return cmd_export(config, args.ministry, args.brain)
    return cmd_status(config)


if __name__ == "__main__":
    sys.exit(main())
