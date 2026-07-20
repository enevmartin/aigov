"""Deterministic fake brain for tests and --dry-run.

Produces contract-valid output for EVERY task type, derived purely from
``task.yaml`` and the ``input/`` listing — same task in, byte-identical
artifacts out. Lets the whole pipeline (and local development) run without
spending a single token.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from brains.base import ArtifactSet
from core.contracts import REQUIRED_ARTIFACTS, TaskSpec, TaskType


def approve_marker(task_dir: Path) -> None:
    """Test utility: stamp a task as review-approved (bypasses a session)."""
    marker = {"verdict": "approve", "notes": [], "reviewer": "test-approver"}
    (task_dir / "review.json").write_text(
        json.dumps(marker, ensure_ascii=False), encoding="utf-8"
    )


FAKE_SOURCE = {
    "url": "https://example.bg/fake-source",
    "title": "Тестов източник (fake brain)",
    "retrieved": None,  # filled per task below
}


class FakeBrain:
    """A :class:`brains.base.BrainAdapter` that fabricates plausible output."""

    def run(self, task_dir: Path) -> ArtifactSet:
        """Write deterministic, contract-valid artifacts into ``output/``."""
        spec = TaskSpec.model_validate(
            yaml.safe_load((task_dir / "task.yaml").read_text(encoding="utf-8"))
        )
        input_files = sorted(
            p.relative_to(task_dir / "input").as_posix()
            for p in (task_dir / "input").rglob("*")
            if p.is_file()
        )
        day = spec.created.date().isoformat()
        source = {**FAKE_SOURCE, "retrieved": day}

        output = task_dir / "output"
        output.mkdir(exist_ok=True)
        required = REQUIRED_ARTIFACTS[spec.type]

        if "report.md" in required:
            self._write_report(output, spec, day, source, input_files)
        if "aggregates.json" in required:
            self._write_aggregates(output, spec, day, source, input_files)
        if "news.json" in required:
            self._write_news(output, spec, day, source)
        if "signals.json" in required:
            self._write_signals(output, spec, day)
        if "review.json" in required:
            self._write_review(output)

        return ArtifactSet.from_output_dir(output)

    def _write_review(self, output: Path) -> None:
        """The fake reviewer approves deterministically (tests override this)."""
        review = {"verdict": "approve", "notes": [], "reviewer": "fake-brain"}
        (output / "review.json").write_text(
            json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _write_report(
        self,
        output: Path,
        spec: TaskSpec,
        day: str,
        source: dict[str, Any],
        input_files: list[str],
    ) -> None:
        front: dict[str, Any] = {
            "ministry": spec.ministry,
            "date": day,
            "title": f"Тестов отчет: {spec.ministry} / {spec.type.value}",
            "summary": f"Детерминистичен тестов отчет върху {len(input_files)} входни файла.",
            "sources": [source],
        }
        if spec.type is TaskType.CRISIS_BRIEF:
            front["confidence"] = "medium"
            front["trigger_keywords"] = ["тест"]
        if spec.type is TaskType.JOINT_REPORT:
            # contributors derived from input/ layout: input/published/{slug}/...
            slugs = sorted({name.split("/")[1] for name in input_files if "/" in name})
            front["contributors"] = slugs if len(slugs) >= 2 else ["finance", "health"]
        body = (
            f"## Анализ\n\nЗадача `{spec.id}` от тип `{spec.type.value}`.\n\n"
            + "Входни файлове:\n"
            + "".join(f"- `{name}`\n" for name in input_files)
        )
        front_yaml = yaml.safe_dump(front, allow_unicode=True, sort_keys=False)
        (output / "report.md").write_text(f"---\n{front_yaml}---\n\n{body}", encoding="utf-8")

    def _write_aggregates(
        self,
        output: Path,
        spec: TaskSpec,
        day: str,
        source: dict[str, Any],
        input_files: list[str],
    ) -> None:
        aggregates = {
            "ministry": spec.ministry,
            "date": day,
            "series": [
                {
                    "name": "Брой входни файлове",
                    "unit": "бр.",
                    "labels": [day],
                    "values": [float(len(input_files))],
                    "source": source,
                }
            ],
        }
        (output / "aggregates.json").write_text(
            json.dumps(aggregates, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _write_news(
        self, output: Path, spec: TaskSpec, day: str, source: dict[str, Any]
    ) -> None:
        news = {
            "ministry": spec.ministry,
            "date": day,
            "items": [
                {
                    "title": "Тестова новина",
                    "summary": f"Резюме от фалшивия мозък за {spec.ministry}.",
                    "source": source,
                }
            ],
        }
        (output / "news.json").write_text(
            json.dumps(news, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _write_signals(self, output: Path, spec: TaskSpec, day: str) -> None:
        signals = {
            "ministry": spec.ministry,
            "date": day,
            "total": 3,
            "categories": [
                {"category": "инфраструктура", "count": 2},
                {"category": "административно обслужване", "count": 1},
            ],
            "note": "Детерминистична тестова агрегация (fake brain).",
        }
        (output / "signals.json").write_text(
            json.dumps(signals, ensure_ascii=False, indent=2), encoding="utf-8"
        )
