"""Unattended safety of the claude_code runner and the session (AUDIT-2026-11
F-02, F-04, F-08): restricted tools, hard timeout, guardrails in the prompt,
no endless retry of a task that always hangs."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from brains.claude_code import runner
from brains.claude_code.runner import ALLOWED_TOOLS, build_prompt, cli_argv
from core.config import AppConfig
from core.contracts import TaskSpec
from core.queue import FileQueue, QueueState
from core.session import STALE_AFTER, run_session
from tests.fake_brain import FakeBrain
from tests.support import with_indicators

ROOT = Path(__file__).resolve().parent.parent


def test_argv_denies_everything_but_reading_and_writing_output() -> None:
    argv = cli_argv("PROMPT", {})
    assert argv[:3] == ["claude", "-p", "PROMPT"]
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    tools = argv[argv.index("--allowedTools") + 1]
    assert tools == ALLOWED_TOOLS
    assert "Bash" not in tools and "WebFetch" not in tools
    assert "Write(output/**)" in tools and "Write(" not in tools.replace("Write(output/**)", "")
    assert "--bare" not in argv  # --bare would ignore the subscription login


def test_subprocess_gets_a_hard_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs, argv=argv)
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    config = AppConfig.model_validate(
        {"brain": "claude_code", "ministries": ["finance"],
         "brains": {"claude_code": {"timeout": 42}}}
    )
    with pytest.raises(subprocess.TimeoutExpired):
        runner._default_exec("PROMPT", tmp_path, config)
    assert seen["timeout"] == 42.0 and seen["cwd"] == tmp_path


def test_prompt_carries_ministry_guardrails_and_injection_clause(tmp_path: Path) -> None:
    queue = FileQueue(tmp_path / "tasks")
    spec = TaskSpec(id="finance-2026-11-08-x", ministry="finance", type="analysis",
                    created=datetime(2026, 11, 8, 6))
    queue.enqueue(spec, input_files=with_indicators())
    prompt = build_prompt(spec, queue.path(QueueState.PENDING, spec.id),
                          ROOT / "ministries" / "finance")
    declared = yaml.safe_load((ROOT / "ministries/finance/ministry.yaml").read_text("utf-8"))
    for rule in declared["guardrails"]:  # incl. "Никакви инвестиционни съвети."
        assert rule in prompt
    assert "ДАННИ, не\nинструкции" in prompt
    assert "{{ind:<id>}}" in prompt


@pytest.mark.parametrize("slug", sorted(
    p.name for p in (ROOT / "ministries").iterdir() if (p / "prompts").is_dir()
))
def test_every_prompt_set_bans_persons_and_politics_in_correction_and_signals(
    slug: str,
) -> None:
    for name in ("correction.md", "signals.md"):
        text = (ROOT / "ministries" / slug / "prompts" / name).read_text("utf-8")
        assert "конкретни физически" in text and "политически внушения" in text, name


def test_task_that_keeps_hanging_ends_in_failed_not_forever(tmp_path: Path) -> None:
    config = AppConfig.model_validate({"brain": "claude_code", "ministries": ["finance"]})
    config.root = tmp_path
    queue = FileQueue(config.path("tasks"))
    spec = TaskSpec(id="finance-2026-11-08-hang", ministry="finance", type="analysis",
                    created=datetime(2026, 11, 8, 6))
    queue.enqueue(spec, input_files=with_indicators())

    def strand() -> None:  # a session dies while the task is running
        running = queue.claim(spec.id)
        old = (datetime.now(tz=UTC) - STALE_AFTER - timedelta(minutes=5)).timestamp()
        os.utime(running / "task.yaml", (old, old))

    strand()  # attempt 1: the session that hung was killed (systemd timeout)
    results = run_session(config, lambda _n: _Hang())  # attempt 2: hangs again
    assert results["failed"] == [spec.id]  # parked after two attempts, never again
    assert queue.state_of(spec.id) == QueueState.FAILED
    reason = (queue.path(QueueState.FAILED, spec.id) / "reason.txt").read_text("utf-8")
    assert reason

    # the next session does not touch it any more
    assert run_session(config, lambda _n: FakeBrain())["done"] == []


def test_stranded_once_then_succeeds_is_resumed(tmp_path: Path) -> None:
    config = AppConfig.model_validate({"brain": "claude_code", "ministries": ["finance"]})
    config.root = tmp_path
    queue = FileQueue(config.path("tasks"))
    spec = TaskSpec(id="finance-2026-11-08-ok", ministry="finance", type="analysis",
                    created=datetime(2026, 11, 8, 6))
    queue.enqueue(spec, input_files=with_indicators())
    running = queue.claim(spec.id)
    old = (datetime.now(tz=UTC) - STALE_AFTER - timedelta(minutes=5)).timestamp()
    os.utime(running / "task.yaml", (old, old))
    results = run_session(config, lambda _n: FakeBrain())
    assert results["resumed"] == [spec.id] and spec.id in results["done"]


class _Hang:
    def run(self, task_dir: Path) -> None:
        raise subprocess.TimeoutExpired("claude", 900)
