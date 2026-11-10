"""``aigov-data`` — operator commands for the tier-1 indicator registry.

    aigov-data verify  [--ministry SLUG] [--record]   live check, writes YAML
    aigov-data collect [--ministry SLUG]              fetch + compute -> data/indicators/
    aigov-data watch-verify                           live check of watchers.yaml
    aigov-data watch                                  new official documents -> event_analysis
    aigov-data respond                                media signals -> search tier 1/2 only

Kept apart from ``aigov`` (core/cli.py) so the data pipeline has its own
entry point. All network access goes through core.net.PoliteClient.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from core.indicators.live import collect, verify_registry_file, write_summaries
from core.indicators.models import load_registry, registry_path
from core.net import PoliteClient

FIXTURES = Path("tests") / "fixtures" / "indicators"


def _slugs(root: Path, only: str | None) -> list[str]:
    if only:
        return [only]
    return sorted(
        p.parent.name
        for p in (root / "ministries").glob("*/indicators.yaml")
        if not p.parent.name.startswith("_")
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aigov-data")
    parser.add_argument("--root", type=Path, default=Path("."))
    sub = parser.add_subparsers(dest="command", required=True)
    p_verify = sub.add_parser("verify", help="live-check every declared indicator")
    p_verify.add_argument("--ministry")
    p_verify.add_argument("--record", action="store_true", help="save payloads as fixtures")
    p_collect = sub.add_parser("collect", help="fetch + compute enabled indicators")
    p_collect.add_argument("--ministry")
    sub.add_parser("watch-verify", help="live-check every tier-2 watcher")
    sub.add_parser("watch", help="new official documents -> event_analysis tasks")
    sub.add_parser("respond", help="media signals -> official (tier 1/2) material or nothing")
    args = parser.parse_args(argv)

    root: Path = args.root
    if args.command in ("watch-verify", "watch", "respond"):
        return _watch(root, args.command)
    today = datetime.now(tz=UTC).date()
    with PoliteClient() as client:
        for slug in _slugs(root, args.ministry):
            if args.command == "verify":
                fixtures = root / FIXTURES if args.record else None
                if fixtures:
                    fixtures.mkdir(parents=True, exist_ok=True)
                reg = verify_registry_file(
                    registry_path(root / "ministries", slug), client, today, fixtures
                )
                for spec in reg.indicators:
                    v = spec.verification
                    state = "ENABLED " if spec.enabled else "disabled"
                    print(
                        f"{state} {spec.id:<34} http={v.http_status if v else '-'} "
                        f"robots={v.robots if v else '-'} latest={v.latest_period if v else '-'}"
                        + ("" if spec.enabled else f"  reason: {spec.disabled_reason}")
                    )
            else:
                reg_or_none = load_registry(root / "ministries", slug)
                if reg_or_none is None:
                    continue
                summaries = collect(reg_or_none, lambda u: client.get(u).content, today)
                write_summaries(summaries, root / "data" / "indicators" / f"{slug}.json")
                print(f"[{slug}] collected {len(summaries)} indicators")
        if args.command == "verify":
            print(f"requests sent: {len(client.log.entries)}")
    return 0


def _watch(root: Path, command: str) -> int:
    import json

    from core.config import load_config
    from core.queue import FileQueue
    from core.watchers import enqueue_event_analysis, fetch_document, load_watchers, scan
    from core.watchers.watch import verify_watchers_file

    today = datetime.now(tz=UTC).date()
    with PoliteClient() as client:
        if command == "watch-verify":
            reg = verify_watchers_file(root / "watchers.yaml", client.get, client.allowed, today)
            for w in reg.watchers:
                v = w.verification
                state = "ENABLED " if w.enabled else "disabled"
                print(
                    f"{state} {w.id:<24} http={v.http_status if v else '-'} "
                    f"robots={v.robots if v else '-'} items={v.items if v else '-'}"
                    + ("" if w.enabled else f"  reason: {w.disabled_reason}")
                )
            print(f"requests sent: {len(client.log.entries)}")
            return 0
        config = load_config(root.resolve())
        active = {m.slug for m in config.enabled_ministries()}
        if command == "respond":
            from core.triggers import open_signals, respond

            def indicators_for(slug: str) -> list[dict[str, object]]:
                path = root / "data" / "indicators" / f"{slug}.json"
                return json.loads(path.read_text("utf-8")) if path.is_file() else []

            signals = [s for s in open_signals(root) if s.ministry in active]
            for o in respond(
                root,
                signals,
                load_watchers(root),
                lambda u: client.get(u).content,
                indicators_for,
                FileQueue(config.path("tasks")),
                today,
            ):
                print(f"[{o['ministry']}] '{o['keyword']}': {o['result']} {o.get('task', '')}")
            return 0
        seen_path = root / "data" / "watchers" / "seen.json"
        seen: set[str] = (
            set(json.loads(seen_path.read_text("utf-8"))) if seen_path.is_file() else set()
        )
        found = scan(load_watchers(root), lambda u: client.get(u).content, seen)
        queue = FileQueue(config.path("tasks"))
        for doc, slugs in found:
            targets = [s for s in slugs if s in active]
            if not targets:
                continue
            document = fetch_document(doc, lambda u: client.get(u).content, today)
            for slug in targets:
                path = root / "data" / "indicators" / f"{slug}.json"
                summaries = json.loads(path.read_text("utf-8")) if path.is_file() else []
                task = enqueue_event_analysis(queue, slug, document, summaries)
                print(
                    f"[{slug}] {doc.kind}: {doc.title[:70]} -> {task or 'skipped (no tier-1 data)'}"
                )
        seen_path.parent.mkdir(parents=True, exist_ok=True)
        seen_path.write_text(json.dumps(sorted(seen), ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
