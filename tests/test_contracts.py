"""Contract schema tests — the interface every brain must satisfy."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.contracts import (
    Aggregates,
    AggregateSeries,
    NewsDigest,
    NewsItem,
    Report,
    SourceCitation,
    TaskSpec,
    TaskType,
    export_json_schemas,
)

CITATION = {
    "url": "https://www.bnb.bg/Statistics/",
    "title": "БНБ — статистика",
    "retrieved": "2026-07-19",
}


def make_task(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "finance-2026-07-19-news",
        "ministry": "finance",
        "type": "news_digest",
        "created": "2026-07-19T06:00:00",
    }
    base.update(overrides)
    return base


class TestTaskSpec:
    def test_valid_minimal(self) -> None:
        task = TaskSpec.model_validate(make_task())
        assert task.type is TaskType.NEWS_DIGEST
        assert task.deadline is None

    def test_valid_with_deadline(self) -> None:
        task = TaskSpec.model_validate(make_task(deadline="2026-07-19T18:00:00"))
        assert task.deadline == datetime(2026, 7, 19, 18, 0)

    def test_deadline_before_created_rejected(self) -> None:
        with pytest.raises(ValidationError, match="deadline must be after created"):
            TaskSpec.model_validate(make_task(deadline="2026-07-19T05:00:00"))

    @pytest.mark.parametrize("bad_id", ["", "UPPER", "има кирилица", "-leading-dash", "a b"])
    def test_bad_ids_rejected(self, bad_id: str) -> None:
        with pytest.raises(ValidationError):
            TaskSpec.model_validate(make_task(id=bad_id))

    def test_unknown_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskSpec.model_validate(make_task(type="propaganda"))

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskSpec.model_validate(make_task(surprise="field"))


class TestReport:
    def test_valid(self) -> None:
        report = Report.model_validate(
            {
                "ministry": "finance",
                "date": "2026-07-19",
                "title": "Месечен анализ на инфлацията",
                "summary": "Инфлацията се забавя за трети пореден месец.",
                "sources": [CITATION],
            }
        )
        assert report.date == date(2026, 7, 19)
        assert str(report.sources[0].url).startswith("https://www.bnb.bg")

    def test_report_without_sources_rejected(self) -> None:
        """Legal guardrail: no citations -> invalid, never published."""
        with pytest.raises(ValidationError):
            Report.model_validate(
                {
                    "ministry": "finance",
                    "date": "2026-07-19",
                    "title": "Без източници",
                    "summary": "…",
                    "sources": [],
                }
            )

    def test_citation_requires_valid_url(self) -> None:
        with pytest.raises(ValidationError):
            SourceCitation.model_validate(
                {"url": "not-a-url", "title": "x", "retrieved": "2026-07-19"}
            )


class TestAggregates:
    def make_series(self, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "name": "Инфлация (%)",
            "unit": "%",
            "labels": ["2026-05", "2026-06", "2026-07"],
            "values": [3.1, 2.8, 2.6],
            "source": CITATION,
        }
        base.update(overrides)
        return base

    def test_valid(self) -> None:
        agg = Aggregates.model_validate(
            {"ministry": "finance", "date": "2026-07-19", "series": [self.make_series()]}
        )
        assert agg.series[0].values == [3.1, 2.8, 2.6]

    def test_mismatched_labels_values_rejected(self) -> None:
        with pytest.raises(ValidationError, match="same length"):
            AggregateSeries.model_validate(self.make_series(values=[1.0, 2.0]))

    def test_empty_series_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Aggregates.model_validate(
                {"ministry": "finance", "date": "2026-07-19", "series": []}
            )


class TestNewsDigest:
    def test_valid(self) -> None:
        digest = NewsDigest.model_validate(
            {
                "ministry": "finance",
                "date": "2026-07-19",
                "items": [
                    {
                        "title": "БНБ запазва основния лихвен процент",
                        "summary": "Централната банка остави ОЛП без промяна.",
                        "source": CITATION,
                    }
                ],
            }
        )
        assert len(digest.items) == 1

    def test_item_without_source_rejected(self) -> None:
        """Every news item must carry its citation."""
        with pytest.raises(ValidationError):
            NewsItem.model_validate({"title": "Новина", "summary": "…"})

    def test_empty_digest_rejected(self) -> None:
        with pytest.raises(ValidationError):
            NewsDigest.model_validate(
                {"ministry": "finance", "date": "2026-07-19", "items": []}
            )


class TestJsonSchemaExport:
    def test_exports_all_schemas(self, tmp_path: Path) -> None:
        written = export_json_schemas(tmp_path)
        names = sorted(p.name for p in written)
        assert names == [
            "aggregates.schema.json",
            "crisis_report.schema.json",
            "health.schema.json",
            "joint_report.schema.json",
            "news.schema.json",
            "report.schema.json",
            "signals.schema.json",
            "task.schema.json",
        ]
        for p in written:
            schema = json.loads(p.read_text(encoding="utf-8"))
            assert "properties" in schema

    def test_export_is_idempotent(self, tmp_path: Path) -> None:
        first = {p.name: p.read_text(encoding="utf-8") for p in export_json_schemas(tmp_path)}
        second = {p.name: p.read_text(encoding="utf-8") for p in export_json_schemas(tmp_path)}
        assert first == second
