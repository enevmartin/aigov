"""Deterministic fake brain for tests and --dry-run.

Produces contract-valid output derived purely from ``task.yaml`` and the
``input/`` listing — same task in, byte-identical artifacts out. Lets the
whole pipeline (and local development) run without spending a single token.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from brains.base import ArtifactSet
from core.contracts import TaskSpec, TaskType

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

        report_front = {
            "ministry": spec.ministry,
            "date": day,
            "title": f"Тестов отчет: {spec.ministry} / {spec.type.value}",
            "summary": f"Детерминистичен тестов отчет върху {len(input_files)} входни файла.",
            "sources": [source],
        }
        body = (
            f"## Анализ\n\nЗадача `{spec.id}` от тип `{spec.type.value}`.\n\n"
            + "Входни файлове:\n"
            + "".join(f"- `{name}`\n" for name in input_files)
        )
        front = yaml.safe_dump(report_front, allow_unicode=True, sort_keys=False)
        (output / "report.md").write_text(f"---\n{front}---\n\n{body}", encoding="utf-8")

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

        if spec.type is TaskType.NEWS_DIGEST:
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

        return ArtifactSet.from_output_dir(output)
