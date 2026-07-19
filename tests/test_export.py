"""Ministry exporters: one declaration -> every orchestration format."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from brains.api.exporter import export_ministry as export_api
from brains.claude_code.exporter import export_ministry as export_claude
from brains.openclaw.exporter import export_ministry as export_openclaw
from core.cli import main
from core.config import AppConfig

MINISTRY_YAML = {
    "name": "Министерство на финансите",
    "slug": "finance",
    "minister_persona": {"име": "Финвест", "стил": "спокоен, компетентен"},
    "sources": {"rss": []},
    "guardrails": ["Всяко твърдение цитира източник (URL + дата на извличане)."],
}


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    ministry = tmp_path / "ministries" / "finance"
    (ministry / "prompts").mkdir(parents=True)
    (ministry / "ministry.yaml").write_text(
        yaml.safe_dump(MINISTRY_YAML, allow_unicode=True), encoding="utf-8"
    )
    (ministry / "prompts" / "news.md").write_text("Резюмирай новините.", encoding="utf-8")
    (ministry / "prompts" / "analysis.md").write_text("Анализирай данните.", encoding="utf-8")
    cfg = AppConfig.model_validate(
        {
            "brain": "claude_code",
            "ministries": ["finance"],
            "brains": {"api": {"model": "deepseek-v4-flash", "fallback": "kimi-k2.6"}},
        }
    )
    cfg.root = tmp_path
    return cfg


def test_claude_code_export_is_a_subagent_definition(config: AppConfig) -> None:
    [target] = export_claude(config, "finance")
    assert target == config.root / ".claude" / "agents" / "finance.md"
    text = target.read_text(encoding="utf-8")
    assert text.startswith("---\nname: finance-minister\n")
    assert "Министерство на финансите" in text
    assert "Финвест" in text                        # persona travels with the agent
    assert "Резюмирай новините." in text            # prompts inlined
    assert "цитира източник" in text                # guardrails inlined
    assert "output/report.md" in text               # contract instructions


def test_openclaw_export_is_a_skill_package(config: AppConfig) -> None:
    written = export_openclaw(config, "finance")
    package = config.root / "export" / "openclaw" / "finance"
    names = {p.relative_to(package).as_posix() for p in written}
    assert names == {"skill.json", "SKILL.md", "prompts/analysis.md", "prompts/news.md"}

    manifest = json.loads((package / "skill.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "aigov-finance-minister"
    assert manifest["language"] == "bg"
    assert "task.yaml" in manifest["contract"]["input"]
    assert "Финвест" in (package / "SKILL.md").read_text(encoding="utf-8")


def test_api_export_is_system_prompt_plus_tools(config: AppConfig) -> None:
    [target] = export_api(config, "finance")
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["model"] == "deepseek-v4-flash"
    assert artifact["fallback"] == "kimi-k2.6"
    assert "Финвест" in artifact["system_prompt"]
    assert "Анализирай данните." in artifact["system_prompt"]
    tool_names = {tool["name"] for tool in artifact["tools"]}
    assert tool_names == {"write_report", "write_aggregates", "write_news"}


def test_cli_export_command(config: AppConfig, capsys: pytest.CaptureFixture[str]) -> None:
    (config.root / "config.yaml").write_text(
        yaml.safe_dump(
            {"brain": "claude_code", "ministries": ["finance"], "brains": {}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    code = main(
        ["--root", str(config.root), "export", "--ministry", "finance", "--brain", "openclaw"]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "skill.json" in out
    assert (config.root / "export" / "openclaw" / "finance" / "skill.json").is_file()
