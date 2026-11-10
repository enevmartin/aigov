"""claude_code brain tests — the CLI subprocess is always faked."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from brains.claude_code.runner import ClaudeCodeBrain, build_prompt, run_cabinet_session
from core.config import AppConfig
from core.contracts import TaskSpec
from core.queue import FileQueue, QueueState
from tests.support import with_indicators

MINISTRY_YAML = {
    "name": "Министерство на финансите",
    "minister_persona": {
        "име": "Финанциера",
        "стил": "компетентен, спокоен, без политически пристрастия",
    },
}


@pytest.fixture
def repo(tmp_path: Path) -> AppConfig:
    """A miniature aigov repo: config + one ministry + queue dirs."""
    ministry = tmp_path / "ministries" / "finance"
    (ministry / "prompts").mkdir(parents=True)
    (ministry / "ministry.yaml").write_text(
        yaml.safe_dump(MINISTRY_YAML, allow_unicode=True), encoding="utf-8"
    )
    (ministry / "prompts" / "news.md").write_text(
        "Резюмирай новините неутрално, с източници.", encoding="utf-8"
    )
    (ministry / "prompts" / "analysis.md").write_text(
        "Анализирай данните задълбочено.", encoding="utf-8"
    )
    config = AppConfig.model_validate(
        {"brain": "claude_code", "ministries": ["finance"], "brains": {"claude_code": {}}}
    )
    config.root = tmp_path
    return config


def make_spec(
    task_id: str = "finance-2026-07-19-digest", task_type: str = "analysis"
) -> TaskSpec:
    return TaskSpec.model_validate(
        {"id": task_id, "ministry": "finance", "type": task_type, "created": "2026-07-19T06:00:00"}
    )


def enqueue(config: AppConfig, spec: TaskSpec) -> FileQueue:
    queue = FileQueue(config.path("tasks"))
    queue.enqueue(spec, input_files=with_indicators({"staging/rss.parquet": b"data"}))
    return queue


class TestBuildPrompt:
    def test_contains_all_components(self, repo: AppConfig) -> None:
        spec = make_spec()
        queue = enqueue(repo, spec)
        task_dir = queue.path(QueueState.PENDING, spec.id)
        prompt = build_prompt(spec, task_dir, repo.ministry_dir("finance"))

        assert "Министерство на финансите" in prompt          # ministry.yaml
        assert "без политически пристрастия" in prompt         # persona
        assert "Анализирай данните задълбочено" in prompt      # prompts/analysis.md
        assert "input/indicators.json" in prompt               # input listing
        assert "output/report.md" in prompt                    # contract
        assert "{{ind:<id>}}" in prompt                        # чл. 8: references only
        assert "непроверими обвинения" in prompt               # legal guardrails

    def test_analysis_type_uses_analysis_prompt(self, repo: AppConfig) -> None:
        spec = make_spec("finance-2026-07-19-an", "analysis")
        queue = enqueue(repo, spec)
        prompt = build_prompt(
            spec, queue.path(QueueState.PENDING, spec.id), repo.ministry_dir("finance")
        )
        assert "Анализирай данните задълбочено" in prompt


class TestClaudeCodeBrain:
    def test_invokes_exec_and_collects_artifacts(self, repo: AppConfig) -> None:
        spec = make_spec()
        queue = enqueue(repo, spec)
        running = queue.claim(spec.id)
        calls: list[tuple[str, Path]] = []

        def fake_exec(prompt: str, task_dir: Path, config: AppConfig) -> None:
            calls.append((prompt, task_dir))
            out = task_dir / "output"
            (out / "report.md").write_text("---\n---\n", encoding="utf-8")
            (out / "aggregates.json").write_text("{}", encoding="utf-8")
            (out / "news.json").write_text("{}", encoding="utf-8")

        artifacts = ClaudeCodeBrain(repo, exec_fn=fake_exec).run(running)
        assert len(calls) == 1
        assert calls[0][1] == running                      # cwd = task dir
        assert "сесия на кабинета" in calls[0][0]
        assert artifacts.report == running / "output" / "report.md"

    def test_missing_artifacts_raise(self, repo: AppConfig) -> None:
        spec = make_spec()
        queue = enqueue(repo, spec)
        running = queue.claim(spec.id)

        def lazy_exec(prompt: str, task_dir: Path, config: AppConfig) -> None:
            pass  # writes nothing at all

        with pytest.raises(RuntimeError, match="report.md"):
            ClaudeCodeBrain(repo, exec_fn=lazy_exec).run(running)


class TestCabinetSession:
    def test_batch_processes_all_pending(self, repo: AppConfig) -> None:
        queue = FileQueue(repo.path("tasks"))
        for i in range(3):
            queue.enqueue(make_spec(f"finance-2026-07-19-t{i}"), input_files=with_indicators())

        results = run_cabinet_session(repo, dry_run=True)
        assert sorted(results["done"]) == [f"finance-2026-07-19-t{i}" for i in range(3)]
        assert results["failed"] == []
        assert queue.list_tasks(QueueState.PENDING) == []
        assert len(queue.list_tasks(QueueState.DONE)) == 3

    def test_one_failure_does_not_stop_the_session(self, repo: AppConfig) -> None:
        queue = FileQueue(repo.path("tasks"))
        queue.enqueue(make_spec("finance-2026-07-19-ok"), input_files=with_indicators())
        broken = queue.enqueue(make_spec("finance-2026-07-19-broken"))
        (broken / "task.yaml").write_text("ministry: [broken", encoding="utf-8")

        # session 1: the broken task is retried (not yet failed), ok completes
        results = run_cabinet_session(repo, dry_run=True)
        assert results["done"] == ["finance-2026-07-19-ok"]
        assert results["retried"] == ["finance-2026-07-19-broken"]

        # session 2: second failure -> failed/ with the reason recorded
        results = run_cabinet_session(repo, dry_run=True)
        assert results["failed"] == ["finance-2026-07-19-broken"]
        reason = (
            queue.path(QueueState.FAILED, "finance-2026-07-19-broken") / "reason.txt"
        ).read_text(encoding="utf-8")
        assert reason  # cause recorded for the operator

    def test_dry_run_output_is_contract_valid_fake(self, repo: AppConfig) -> None:
        queue = FileQueue(repo.path("tasks"))
        queue.enqueue(make_spec(), input_files=with_indicators())
        run_cabinet_session(repo, dry_run=True)
        output = queue.path(QueueState.DONE, "finance-2026-07-19-digest") / "output"
        report = (output / "report.md").read_text(encoding="utf-8")
        assert "Тестов отчет" in report                     # fake brain, not the CLI
        assert "{{ind:finance.hicp_annual}}" in report       # references, never numbers
        assert not (output / "aggregates.json").exists()
