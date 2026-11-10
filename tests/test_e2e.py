"""End-to-end: recorded tier-1 payload -> collector -> task -> fake brain -> valid output.

No network, no LLM. The numbers the minister may talk about are computed by
the collector from a RECORDED official payload; the brain only references them.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import frontmatter

from brains.base import ArtifactSet, BrainAdapter
from core.contracts import (
    Report,
    TaskSpec,
    TierRegistry,
    indicator_refs,
    validate_evidence,
)
from core.indicators import load_registry, parse, summarize
from core.queue import FileQueue, QueueState
from tests.fake_brain import FakeBrain

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "indicators"


def test_fake_brain_satisfies_the_port() -> None:
    assert isinstance(FakeBrain(), BrainAdapter)


def _collected() -> list[dict[str, object]]:
    registry = load_registry(ROOT / "ministries", "finance")
    assert registry is not None
    spec = registry.get("finance.hicp_annual")
    assert spec is not None
    rows = parse(spec, (FIXTURES / "finance.hicp_annual.json").read_bytes())
    return [summarize(spec, rows, today=date(2026, 11, 8)).model_dump(mode="json")]


def test_full_pipeline_with_fake_brain(tmp_path: Path) -> None:
    # --- 1. collector: recorded Eurostat payload -> computed summary --------
    summaries = _collected()
    assert summaries[0]["period"] == "2026-10"

    # --- 2. enqueue: the collector's numbers become the task's input --------
    queue = FileQueue(tmp_path / "tasks")
    spec = TaskSpec.model_validate(
        {
            "id": "finance-2026-11-08-analysis",
            "ministry": "finance",
            "type": "analysis",
            "created": "2026-11-08T06:00:00",
        }
    )
    queue.enqueue(
        spec, input_files={"indicators.json": json.dumps(summaries, ensure_ascii=False).encode()}
    )

    # --- 3. brain: claim -> run -> complete -------------------------------
    running = queue.claim(spec.id)
    artifacts = FakeBrain().run(running)
    done = queue.complete(spec.id)
    assert queue.state_of(spec.id) == QueueState.DONE

    # --- 4. output obeys the contract AND чл. 8 ------------------------------
    output = done / "output"
    post = frontmatter.loads((output / "report.md").read_text(encoding="utf-8"))
    report = Report.model_validate(post.metadata)
    assert report.ministry == "finance"
    assert [s.url.host for s in report.sources] == ["ec.europa.eu"]
    assert ("finance.hicp_annual", "value") in indicator_refs(post.content)
    indicators = {str(s["id"]): s for s in summaries}
    validate_evidence(post.metadata, post.content, indicators, TierRegistry.load(ROOT))
    assert not (output / "aggregates.json").exists()  # numbers are never the brain's

    assert artifacts.report is not None
    assert ArtifactSet.from_output_dir(output).report == output / "report.md"


def test_fake_brain_is_deterministic(tmp_path: Path) -> None:
    """Same task in -> byte-identical artifacts out (twice)."""
    payload = json.dumps(_collected(), ensure_ascii=False).encode()

    def build_and_run(root: Path) -> dict[str, bytes]:
        queue = FileQueue(root / "tasks")
        spec = TaskSpec.model_validate(
            {
                "id": "finance-2026-07-19-analysis",
                "ministry": "finance",
                "type": "analysis",
                "created": "2026-07-19T06:00:00",
            }
        )
        queue.enqueue(spec, input_files={"indicators.json": payload})
        running = queue.claim(spec.id)
        FakeBrain().run(running)
        return {p.name: p.read_bytes() for p in (running / "output").iterdir()}

    first = build_and_run(tmp_path / "a")
    second = build_and_run(tmp_path / "b")
    assert first == second
    assert set(first) == {"report.md"}
