"""Keep the ministry declarations honest: parseable, complete, code-free."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.config import load_config
from core.contracts import TaskType

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_PROMPTS = {"analysis.md", "news.md", "report.md"}
REQUIRED_KEYS = {"name", "slug", "minister_persona", "sources", "guardrails"}


def ministry_dirs() -> list[Path]:
    return sorted(
        p
        for p in (REPO_ROOT / "ministries").iterdir()
        if p.is_dir() and not p.name.startswith("_")
    )


@pytest.mark.parametrize("ministry_dir", ministry_dirs(), ids=lambda p: p.name)
class TestMinistryDeclarations:
    def test_yaml_parses_with_required_keys(self, ministry_dir: Path) -> None:
        declaration = yaml.safe_load(
            (ministry_dir / "ministry.yaml").read_text(encoding="utf-8")
        )
        missing = REQUIRED_KEYS - declaration.keys()
        assert not missing, f"{ministry_dir.name}/ministry.yaml missing keys: {missing}"
        assert declaration["slug"] == ministry_dir.name

    def test_all_prompt_files_exist(self, ministry_dir: Path) -> None:
        present = {p.name for p in (ministry_dir / "prompts").glob("*.md")}
        assert REQUIRED_PROMPTS <= present

    def test_guardrails_include_source_citation_rule(self, ministry_dir: Path) -> None:
        declaration = yaml.safe_load(
            (ministry_dir / "ministry.yaml").read_text(encoding="utf-8")
        )
        assert any("източник" in rule for rule in declaration["guardrails"])

    def test_no_executable_code_in_ministry(self, ministry_dir: Path) -> None:
        """Invariant #3: ministries are declarations only."""
        code_files = [
            p
            for p in ministry_dir.rglob("*")
            if p.suffix in {".py", ".sh", ".js", ".ts", ".exe", ".bat", ".ps1"}
        ]
        assert code_files == []


class TestConfiguredMinistries:
    def test_every_configured_ministry_has_a_directory(self) -> None:
        config = load_config(REPO_ROOT)
        for slug in config.ministries:
            assert (REPO_ROOT / "ministries" / slug / "ministry.yaml").is_file()

    def test_rss_sources_shape_matches_ingest_expectations(self) -> None:
        """collect_rss needs name+url on every rss entry."""
        config = load_config(REPO_ROOT)
        for slug in config.ministries:
            declaration = yaml.safe_load(
                (REPO_ROOT / "ministries" / slug / "ministry.yaml").read_text(encoding="utf-8")
            )
            for entry in declaration["sources"].get("rss", []):
                assert entry.get("name") and entry.get("url"), entry

    def test_prompt_mapping_covers_all_task_types(self) -> None:
        """Every TaskType must resolve to an existing prompt file."""
        from brains.claude_code.runner import PROMPT_FILES

        config = load_config(REPO_ROOT)
        for slug in config.ministries:
            prompts = REPO_ROOT / "ministries" / slug / "prompts"
            for task_type in TaskType:
                assert (prompts / PROMPT_FILES[task_type]).is_file()
