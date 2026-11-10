"""Deterministic fake brain for tests and --dry-run.

Produces contract-valid output for EVERY task type, derived purely from
``task.yaml`` and the ``input/`` directory — same task in, byte-identical
artifacts out. Lets the whole pipeline (and local development) run without
spending a single token.

Contract v2 (чл. 8): like a real minister it writes NO numbers — only
``{{ind:<id>}}`` references to ``input/indicators.json`` — and cites only
the tier-1 sources of those indicators (or the tier-2 document of an
``event_analysis``). With no indicators in the input it has no evidence, so
its report is left without sources and the publish gate rejects it.
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
    (task_dir / "review.json").write_text(json.dumps(marker, ensure_ascii=False), encoding="utf-8")


class FakeBrain:
    """A :class:`brains.base.BrainAdapter` that fabricates plausible output."""

    def run(self, task_dir: Path) -> ArtifactSet:
        """Write deterministic, contract-valid artifacts into ``output/``."""
        spec = TaskSpec.model_validate(
            yaml.safe_load((task_dir / "task.yaml").read_text(encoding="utf-8"))
        )
        input_dir = task_dir / "input"
        input_files = sorted(
            p.relative_to(input_dir).as_posix() for p in input_dir.rglob("*") if p.is_file()
        )
        day = spec.created.date().isoformat()

        output = task_dir / "output"
        output.mkdir(exist_ok=True)
        required = REQUIRED_ARTIFACTS[spec.type]

        if "report.md" in required:
            self._write_report(output, spec, day, input_dir, input_files)
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
        input_dir: Path,
        input_files: list[str],
    ) -> None:
        indicators: list[dict[str, Any]] = []
        if (input_dir / "indicators.json").is_file():
            indicators = json.loads((input_dir / "indicators.json").read_text(encoding="utf-8"))
        sources = [
            {"url": i["source_page"], "title": f"{i['publisher']}: {i['name']}", "retrieved": day}
            for i in indicators
        ]
        front: dict[str, Any] = {
            "ministry": spec.ministry,
            "date": day,
            "title": f"Тестов отчет: {spec.ministry} / {spec.type.value}",
            "summary": "Детерминистичен тестов отчет върху официалните индикатори.",
            "sources": sources,
        }
        if spec.type is TaskType.EVENT_ANALYSIS:
            document = json.loads((input_dir / "document.json").read_text(encoding="utf-8"))
            front["document"] = {
                k: document[k] for k in ("url", "title", "publisher", "kind", "retrieved", "sha256")
            }
            front["sources"] = [
                {
                    "url": document["url"],
                    "title": document["title"],
                    "retrieved": document["retrieved"],
                },
                *sources,
            ]
        if spec.type is TaskType.CRISIS_BRIEF:
            front["confidence"] = "medium"
            front["trigger_keywords"] = ["тест"]
        if spec.type is TaskType.JOINT_REPORT:
            # contributors derived from input/ layout: input/published/{slug}/...
            slugs = sorted({n.split("/")[1] for n in input_files if n.startswith("published/")})
            front["contributors"] = slugs if len(slugs) >= 2 else ["finance", "health"]
        if spec.type is TaskType.CORRECTION:
            request = json.loads((input_dir / "correction_request.json").read_text("utf-8"))
            front["corrects"] = {
                "ministry": request["ministry"],
                "date": request["date"],
                "type": request.get("type"),
            }
        lines = [
            f"- {i['name']}: {{{{ind:{i['id']}}}}} за {{{{ind:{i['id']}.period}}}} "
            f"(промяна {{{{ind:{i['id']}.change}}}} спрямо {{{{ind:{i['id']}.previous_period}}}})"
            for i in indicators
        ]
        body = (
            f"## Анализ\n\nЗадача `{spec.id}` от тип `{spec.type.value}`.\n\n"
            + ("Официални индикатори:\n" + "\n".join(lines) + "\n" if lines else "")
            + "\nВходни файлове:\n"
            + "".join(f"- `{name}`\n" for name in input_files)
        )
        front_yaml = yaml.safe_dump(front, allow_unicode=True, sort_keys=False)
        (output / "report.md").write_text(f"---\n{front_yaml}---\n\n{body}", encoding="utf-8")

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
