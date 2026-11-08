"""``aigov-data`` — operator commands for the tier-1 indicator registry.

    aigov-data verify  [--ministry SLUG] [--record]   live check, writes YAML
    aigov-data collect [--ministry SLUG]              fetch + compute -> data/indicators/

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
    args = parser.parse_args(argv)

    root: Path = args.root
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


if __name__ == "__main__":
    raise SystemExit(main())
