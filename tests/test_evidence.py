"""Чл. 8 enforced by the publish gate: numbers only via tier-1 references,
no tier-3 (media) source cited as evidence for a fact."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import yaml

from core.config import AppConfig
from core.contracts import (
    EvidenceError,
    TaskSpec,
    TierRegistry,
    check_bare_numbers,
    render_refs,
    validate_evidence,
)
from core.publish import publish_all
from core.queue import FileQueue, QueueState
from tests.fake_brain import FakeBrain, approve_marker
from tests.support import INDICATOR_ID, SOURCE_PAGE, summary, with_indicators

IND = {INDICATOR_ID: summary()}
TIERS = TierRegistry(tier1_urls={SOURCE_PAGE.rstrip("/")}, tier2_hosts={"parliament.bg"})
FRONT = {
    "title": "Инфлацията през октомври",
    "summary": "Кратко резюме без числа.",
    "sources": [{"url": SOURCE_PAGE, "title": "Евростат", "retrieved": "2026-11-08"}],
}


# -- the rules, unit level ---------------------------------------------------
class TestNumbers:
    def test_reference_is_accepted(self) -> None:
        body = f"Инфлацията е {{{{ind:{INDICATOR_ID}}}}} ({{{{ind:{INDICATOR_ID}.change}}}})."
        assert validate_evidence(FRONT, body, IND, TIERS) == [INDICATOR_ID]

    def test_bare_number_without_tier1_reference_is_rejected(self) -> None:
        with pytest.raises(EvidenceError, match="без референция"):
            validate_evidence(FRONT, "Инфлацията е 6,0% през октомври.", IND, TIERS)

    @pytest.mark.parametrize(
        "text", ["нараства с 3 пункта", "дефицит от 1 200 млн. евро", "около 0,5%"]
    )
    def test_numbers_in_any_form_are_rejected(self, text: str) -> None:
        assert check_bare_numbers(text)

    @pytest.mark.parametrize(
        "text",
        [
            "през 2026 г. и Q2",
            "данни към 06.11.2026 г.",
            "периодът 2026-Q2 и 2026-10",
            "съгласно чл. 45, ал. 2 от закона, обнародван в ДВ бр. 43",
            "§ 12 от преходните разпоредби, № 7",
            "идентификатор `finance-2026-11-08-analysis`",
        ],
    )
    def test_non_quantities_are_allowed(self, text: str) -> None:
        assert check_bare_numbers(text) == []

    def test_number_in_title_is_rejected_too(self) -> None:
        with pytest.raises(EvidenceError):
            validate_evidence({**FRONT, "title": "Инфлация 6%"}, "Текст.", IND, TIERS)

    def test_reference_to_indicator_not_in_input_is_rejected(self) -> None:
        with pytest.raises(EvidenceError, match="извън входа"):
            validate_evidence(FRONT, "Стойност {{ind:finance.gov_debt}}.", IND, TIERS)

    def test_render_uses_collector_numbers_in_bulgarian_format(self) -> None:
        text = f"{{{{ind:{INDICATOR_ID}}}}}, {{{{ind:{INDICATOR_ID}.change}}}}"
        assert render_refs(text, IND) == "6 %, +0,4 %"


class TestTiers:
    def test_tier3_media_source_cited_as_fact_is_rejected(self) -> None:
        front = {
            **FRONT,
            "sources": [
                {
                    "url": "https://www.mediapool.bg/news-123.html",
                    "title": "Медия",
                    "retrieved": "2026-11-08",
                }
            ],
        }
        with pytest.raises(EvidenceError, match="ниво 3"):
            validate_evidence(front, "Текст без числа.", IND, TIERS)

    def test_media_is_allowed_only_as_trigger(self) -> None:
        front = {
            **FRONT,
            "trigger": [
                {
                    "url": "https://www.mediapool.bg/news-123.html",
                    "title": "Медия",
                    "retrieved": "2026-11-08",
                }
            ],
        }
        assert validate_evidence(front, "Текст без числа.", IND, TIERS) == []

    def test_tier_comes_from_registry_not_from_the_model(self, tmp_path: Path) -> None:
        (tmp_path / "ministries" / "finance").mkdir(parents=True)
        (tmp_path / "ministries" / "finance" / "indicators.yaml").write_text(
            yaml.safe_dump(
                {
                    "ministry": "finance",
                    "indicators": [
                        {
                            "id": "finance.x",
                            "source": {
                                "url": "https://data.example/x",
                                "page": "https://data.example/p",
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "watchers.yaml").write_text(
            yaml.safe_dump({"watchers": [{"url": "https://www.parliament.bg/feed/bills"}]}),
            encoding="utf-8",
        )
        tiers = TierRegistry.load(tmp_path)
        assert tiers.tier("https://data.example/p") == 1
        assert tiers.tier("https://www.parliament.bg/bg/bills/1") == 2
        assert tiers.tier("https://www.mediapool.bg/x") == 3
        assert tiers.tier("https://data.example/other") == 3  # same host, not declared


# -- the rules, at the publish gate -------------------------------------------
@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig.model_validate({"brain": "claude_code", "ministries": ["finance"]})
    cfg.root = tmp_path
    return cfg


def _done_task(config: AppConfig, body: str, sources: list[dict[str, str]]) -> str:
    queue = FileQueue(config.path("tasks"))
    spec = TaskSpec(
        id="finance-2026-11-08-x",
        ministry="finance",
        type="analysis",
        created=datetime(2026, 11, 8, 6),
    )
    queue.enqueue(spec, input_files=with_indicators())
    task_dir = queue.claim(spec.id)
    (task_dir / "output").mkdir()
    front = {
        "ministry": "finance",
        "date": "2026-11-08",
        "title": "Инфлация",
        "summary": "Резюме.",
        "sources": sources,
    }
    (task_dir / "output" / "report.md").write_text(
        f"---\n{yaml.safe_dump(front, allow_unicode=True)}---\n\n{body}\n", encoding="utf-8"
    )
    approve_marker(task_dir)
    queue.complete(spec.id)
    return spec.id


GOOD_SOURCE = [{"url": SOURCE_PAGE, "title": "Евростат", "retrieved": "2026-11-08"}]


def test_publish_rejects_report_number_without_indicator_reference(config: AppConfig) -> None:
    task_id = _done_task(config, "Инфлацията е 6,0%.", GOOD_SOURCE)
    result = publish_all(config)
    assert result["rejected"] == [task_id]
    reason = (config.path("tasks") / "failed" / task_id / "reason.txt").read_text("utf-8")
    assert "чл. 8" in reason and "без референция" in reason
    assert not (config.path("published") / "finance" / "2026-11-08").exists()


def test_publish_rejects_tier3_source_cited_as_fact(config: AppConfig) -> None:
    media = [
        {"url": "https://www.mediapool.bg/a.html", "title": "Медия", "retrieved": "2026-11-08"}
    ]
    task_id = _done_task(config, f"Стойност {{{{ind:{INDICATOR_ID}}}}}.", media)
    assert publish_all(config)["rejected"] == [task_id]
    reason = (config.path("tasks") / "failed" / task_id / "reason.txt").read_text("utf-8")
    assert "ниво 3" in reason


def test_publish_renders_collector_numbers(config: AppConfig) -> None:
    task_id = _done_task(config, f"Инфлацията е {{{{ind:{INDICATOR_ID}}}}}.", GOOD_SOURCE)
    assert publish_all(config)["published"] == [task_id]
    out = config.path("published") / "finance" / "2026-11-08" / "analysis"
    assert "Инфлацията е 6 %." in (out / "report.md").read_text("utf-8")
    assert (out / "indicators.json").is_file()
    assert (config.path("published") / "finance" / "indicators.json").is_file()


def test_publish_never_overwrites_and_uses_task_date(config: AppConfig) -> None:
    first = _done_task(config, f"А {{{{ind:{INDICATOR_ID}}}}}.", GOOD_SOURCE)
    assert publish_all(config)["published"] == [first]
    second = _done_task(config, f"Б {{{{ind:{INDICATOR_ID}}}}}.", GOOD_SOURCE)
    assert publish_all(config)["rejected"] == [second]
    report = config.path("published") / "finance" / "2026-11-08" / "analysis" / "report.md"
    assert "А 6 %" in report.read_text("utf-8")


def test_fake_brain_report_passes_the_gate(config: AppConfig) -> None:
    queue = FileQueue(config.path("tasks"))
    spec = TaskSpec(
        id="finance-2026-11-08-y",
        ministry="finance",
        type="analysis",
        created=datetime(2026, 11, 8, 6),
    )
    queue.enqueue(spec, input_files=with_indicators())
    task_dir = queue.claim(spec.id)
    FakeBrain().run(task_dir)
    approve_marker(task_dir)
    queue.complete(spec.id)
    assert publish_all(config)["published"] == [spec.id]
    assert queue.state_of(spec.id) is None or queue.state_of(spec.id) != QueueState.FAILED
