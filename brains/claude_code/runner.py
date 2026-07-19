"""Run ministry tasks through the ``claude`` CLI.

For each claimed task the runner assembles one prompt from:

1. the ministry declaration (``ministries/{slug}/ministry.yaml``),
2. the task-type prompt file (``ministries/{slug}/prompts/*.md``),
3. the task spec and the listing of ``input/`` files,
4. the fixed contract instructions (where to write which artifact),

then executes ``claude -p "<prompt>" --output-format json`` with the task
directory as working directory. The CLI session reads ``input/`` and writes
``output/`` itself; the runner only checks the artifacts exist afterwards.

The subprocess call is injectable so tests never launch a real CLI.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import yaml

from brains.base import (
    AGGREGATES_FILE,
    NEWS_FILE,
    OUTPUT_DIR,
    REPORT_FILE,
    ArtifactSet,
    BrainAdapter,
)
from core.config import AppConfig
from core.contracts import TaskSpec, TaskType
from core.session import run_session

# task type -> prompt file inside ministries/{slug}/prompts/
PROMPT_FILES: dict[TaskType, str] = {
    TaskType.ANALYSIS: "analysis.md",
    TaskType.NEWS_DIGEST: "news.md",
    TaskType.SIGNAL_TRIAGE: "analysis.md",  # phase 2; reuse analysis until dedicated prompt
}

CONTRACT_INSTRUCTIONS = """\
## Изходен договор (задължителен)

Работиш в директорията на задачата. Входните данни са в `input/`.
Запиши резултатите САМО в `output/`:

1. `output/report.md` — анализ на български с YAML front-matter:
   `ministry`, `date` (YYYY-MM-DD), `title`, `summary`,
   `sources` (списък от {url, title, retrieved}).
2. `output/aggregates.json` — числата за дашборда; трябва да е валиден срещу
   `expected.schema.json` в директорията на задачата.
3. `output/news.json` — САМО за задачи от тип news_digest: резюмирани новини,
   всяка със своя източник {url, title, retrieved}.

Правни предпазители (ненарушими): всяко твърдение цитира източник (URL + дата
на извличане); никакви твърдения за конкретни лица, политически внушения или
непроверими обвинения. Не пипай нищо извън `output/`.
"""

# Signature of the injectable executor: (prompt, task_dir, config) -> None
ExecFn = Callable[[str, Path, AppConfig], None]


def _default_exec(prompt: str, task_dir: Path, config: AppConfig) -> None:
    """Invoke the real ``claude`` CLI in *task_dir* (blocking)."""
    settings = config.brains.get("claude_code", {})
    cmd = str(settings.get("cmd", "claude"))
    output_format = str(settings.get("output_format", "json"))
    subprocess.run(  # noqa: S603 — fixed argv, no shell
        [cmd, "-p", prompt, "--output-format", output_format],
        cwd=task_dir,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def build_prompt(spec: TaskSpec, task_dir: Path, ministry_dir: Path) -> str:
    """Assemble the full prompt for one task (pure function, testable)."""
    ministry = yaml.safe_load((ministry_dir / "ministry.yaml").read_text(encoding="utf-8"))
    prompt_file = ministry_dir / "prompts" / PROMPT_FILES[spec.type]
    type_prompt = prompt_file.read_text(encoding="utf-8")

    input_dir = task_dir / "input"
    input_listing = sorted(
        p.relative_to(input_dir).as_posix() for p in input_dir.rglob("*") if p.is_file()
    )
    listing = "".join(f"- input/{name}\n" for name in input_listing) or "(няма входни файлове)\n"

    persona = ministry.get("minister_persona", {})
    persona_lines = "".join(f"- {k}: {v}\n" for k, v in persona.items())

    return (
        f"# {ministry['name']} — сесия на кабинета\n\n"
        f"Ти си AI министърът на това министерство.\n{persona_lines}\n"
        f"## Задача\n\n"
        f"- id: {spec.id}\n- тип: {spec.type.value}\n- създадена: {spec.created.isoformat()}\n\n"
        f"## Инструкции за този тип задача\n\n{type_prompt}\n\n"
        f"## Входни файлове\n\n{listing}\n"
        f"{CONTRACT_INSTRUCTIONS}"
    )


class ClaudeCodeBrain:
    """:class:`BrainAdapter` implementation over the ``claude`` CLI."""

    def __init__(self, config: AppConfig, exec_fn: ExecFn | None = None) -> None:
        self.config = config
        self._exec = exec_fn or _default_exec

    def run(self, task_dir: Path) -> ArtifactSet:
        """Build the prompt, run the CLI, and collect the artifacts."""
        spec = TaskSpec.model_validate(
            yaml.safe_load((task_dir / "task.yaml").read_text(encoding="utf-8"))
        )
        ministry_dir = self.config.ministry_dir(spec.ministry)
        prompt = build_prompt(spec, task_dir, ministry_dir)

        output = task_dir / OUTPUT_DIR
        output.mkdir(exist_ok=True)
        self._exec(prompt, task_dir, self.config)

        missing = [
            name
            for name in (REPORT_FILE, AGGREGATES_FILE)
            if not (output / name).is_file()
        ]
        if spec.type is TaskType.NEWS_DIGEST and not (output / NEWS_FILE).is_file():
            missing.append(NEWS_FILE)
        if missing:
            raise RuntimeError(f"brain produced no {', '.join(missing)} in output/")
        return ArtifactSet.from_output_dir(output)


def get_brain(config: AppConfig) -> BrainAdapter:
    """Composition-root hook: return this package's adapter."""
    return ClaudeCodeBrain(config)


def run_cabinet_session(
    config: AppConfig, brain: BrainAdapter | None = None, dry_run: bool = False
) -> dict[str, list[str]]:
    """Process ALL pending tasks in one batch ("cabinet session").

    With ``dry_run=True`` the deterministic fake brain replaces the CLI —
    zero tokens spent, identical file flow. One failing task moves to
    ``failed/`` (with reason) without stopping the rest.

    Returns ``{"done": [...ids], "failed": [...ids]}``.
    """
    if dry_run:
        from tests.fake_brain import FakeBrain  # dev/test dependency, imported lazily

        brain = FakeBrain()
    resolved = brain or ClaudeCodeBrain(config)
    return run_session(config, lambda _name: resolved)
