"""Cabinet observability: sessions.json records and CLI usage parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brains.claude_code.runner import parse_cli_usage
from core.config import AppConfig
from core.contracts import TaskSpec
from core.queue import FileQueue
from core.session import run_session
from tests.fake_brain import FakeBrain


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig.model_validate({"brain": "fake", "ministries": ["finance"]})
    cfg.root = tmp_path
    return cfg


class UsageReportingBrain(FakeBrain):
    """Writes usage.json like the real claude_code exec does."""

    def run(self, task_dir: Path) -> object:
        (task_dir / "usage.json").write_text(
            json.dumps({"input_tokens": 1200, "output_tokens": 340}), encoding="utf-8"
        )
        return super().run(task_dir)


class TestSessionLedger:
    def test_session_records_ministry_type_brain_duration_outcome(
        self, config: AppConfig
    ) -> None:
        queue = FileQueue(config.path("tasks"))
        queue.enqueue(
            TaskSpec.model_validate(
                {
                    "id": "finance-2026-07-20-digest",
                    "ministry": "finance",
                    "type": "news_digest",
                    "created": "2026-07-20T06:00:00",
                }
            )
        )
        run_session(config, lambda _n: UsageReportingBrain())

        payload = json.loads(
            (config.path("published") / "system" / "sessions.json").read_text(
                encoding="utf-8"
            )
        )
        [session] = payload["sessions"]
        by_id = {t["id"]: t for t in session["tasks"]}
        original = by_id["finance-2026-07-20-digest"]
        review = by_id["finance-2026-07-20-digest-review"]

        assert original["ministry"] == "finance"
        assert original["type"] == "news_digest"
        assert original["brain"] == "fake"
        assert original["outcome"] == "done"
        assert original["duration_s"] >= 0
        assert original["tokens"] == {"input_tokens": 1200, "output_tokens": 340}
        assert review["type"] == "review"
        assert review["outcome"] == "approved"

    def test_empty_session_not_recorded(self, config: AppConfig) -> None:
        run_session(config, lambda _n: FakeBrain())
        assert not (config.path("published") / "system" / "sessions.json").exists()

    def test_ledger_is_bounded(self, config: AppConfig) -> None:
        from core.publish.health import MAX_SESSIONS, record_session_details

        for i in range(MAX_SESSIONS + 7):
            record_session_details(config, [{"id": f"t{i}", "duration_s": 0.1, "outcome": "done"}])
        payload = json.loads(
            (config.path("published") / "system" / "sessions.json").read_text(
                encoding="utf-8"
            )
        )
        assert len(payload["sessions"]) == MAX_SESSIONS


class TestUsageParsing:
    def test_parses_usage_and_cost(self) -> None:
        stdout = json.dumps(
            {
                "result": "ok",
                "usage": {
                    "input_tokens": 5000,
                    "output_tokens": 900,
                    "cache_read_input_tokens": 4200,
                    "irrelevant": "x",
                },
                "total_cost_usd": 0.0421,
            }
        )
        assert parse_cli_usage(stdout) == {
            "input_tokens": 5000,
            "output_tokens": 900,
            "cache_read_input_tokens": 4200,
            "total_cost_usd": 0.0421,
        }

    @pytest.mark.parametrize(
        "stdout", ["", "not json", "[]", json.dumps({"result": "ok"}), json.dumps({"usage": 5})]
    )
    def test_foreign_shapes_return_none(self, stdout: str) -> None:
        assert parse_cli_usage(stdout) is None
