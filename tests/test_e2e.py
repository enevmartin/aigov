"""End-to-end: ingest -> enqueue -> fake brain -> contract-valid output.

No network, no LLM. Step 7 (core/publish) extends this flow into
``published/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import frontmatter
import httpx

from brains.base import ArtifactSet, BrainAdapter
from core.contracts import Aggregates, NewsDigest, Report, TaskSpec, export_json_schemas
from core.ingest import ScraperBase, collect_rss
from core.queue import FileQueue, QueueState
from tests.fake_brain import FakeBrain
from tests.test_ingest import RSS_XML


def test_fake_brain_satisfies_the_port() -> None:
    assert isinstance(FakeBrain(), BrainAdapter)


def test_full_pipeline_with_fake_brain(tmp_path: Path) -> None:
    # --- 1. ingest: RSS -> staged parquet (offline transport) -------------
    scraper = ScraperBase(
        min_interval=0, transport=httpx.MockTransport(lambda _: httpx.Response(200, text=RSS_XML))
    )
    result = collect_rss(
        [{"name": "Тест медия", "url": "https://example.bg/rss"}],
        tmp_path / "staging",
        "finance",
        scraper=scraper,
    )
    scraper.close()
    staged = result.staged
    assert staged is not None

    # --- 2. enqueue: staged data becomes a task's input -------------------
    queue = FileQueue(tmp_path / "tasks")
    schemas_dir = tmp_path / "schemas"
    export_json_schemas(schemas_dir)
    spec = TaskSpec.model_validate(
        {
            "id": "finance-2026-07-19-digest",
            "ministry": "finance",
            "type": "news_digest",
            "created": "2026-07-19T06:00:00",
        }
    )
    queue.enqueue(
        spec,
        input_files={f"staging/{staged.name}": staged.read_bytes()},
        expected_schema=(schemas_dir / "aggregates.schema.json").read_text(encoding="utf-8"),
    )

    # --- 3. brain: claim -> run -> complete -------------------------------
    running = queue.claim(spec.id)
    artifacts = FakeBrain().run(running)
    done = queue.complete(spec.id)
    assert queue.state_of(spec.id) == QueueState.DONE

    # --- 4. output validates against the contract -------------------------
    output = done / "output"
    post = frontmatter.loads((output / "report.md").read_text(encoding="utf-8"))
    report = Report.model_validate(post.metadata)
    assert report.ministry == "finance"
    assert report.sources, "legal guardrail: report must cite sources"
    assert "Анализ" in post.content

    aggregates = Aggregates.model_validate(
        json.loads((output / "aggregates.json").read_text(encoding="utf-8"))
    )
    assert aggregates.series[0].values == [1.0]  # exactly one staged input file

    news = NewsDigest.model_validate(json.loads((output / "news.json").read_text(encoding="utf-8")))
    assert news.items[0].source.url is not None

    # ArtifactSet named the same files (dir has since moved running/ -> done/)
    expected = ArtifactSet.from_output_dir(output)
    assert artifacts.report.name == expected.report.name
    assert artifacts.aggregates.name == expected.aggregates.name
    assert artifacts.news is not None and expected.news is not None
    assert artifacts.news.name == expected.news.name


def test_fake_brain_is_deterministic(tmp_path: Path) -> None:
    """Same task in -> byte-identical artifacts out (twice)."""

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
        queue.enqueue(spec, input_files={"data.parquet": b"x"})
        running = queue.claim(spec.id)
        FakeBrain().run(running)
        output = running / "output"
        return {p.name: p.read_bytes() for p in output.iterdir()}

    first = build_and_run(tmp_path / "a")
    second = build_and_run(tmp_path / "b")
    assert first == second
    assert set(first) == {"report.md", "aggregates.json"}  # no news.json for analysis
