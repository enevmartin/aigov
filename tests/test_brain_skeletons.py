"""Skeleton brains must satisfy the port and fail loudly, never silently."""

from __future__ import annotations

from pathlib import Path

import pytest

from brains.api.adapter import ApiBrain
from brains.base import BrainAdapter
from brains.openclaw.adapter import OpenClawBrain
from core.config import AppConfig


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig.model_validate({"brain": "claude_code", "ministries": ["finance"]})
    cfg.root = tmp_path
    return cfg


@pytest.mark.parametrize("brain_cls", [OpenClawBrain, ApiBrain])
def test_skeletons_satisfy_the_port(
    brain_cls: type[OpenClawBrain | ApiBrain], config: AppConfig
) -> None:
    assert isinstance(brain_cls(config), BrainAdapter)


@pytest.mark.parametrize("brain_cls", [OpenClawBrain, ApiBrain])
def test_skeletons_fail_loudly_with_pointer_to_readme(
    brain_cls: type[OpenClawBrain | ApiBrain], config: AppConfig, tmp_path: Path
) -> None:
    with pytest.raises(NotImplementedError, match="README"):
        brain_cls(config).run(tmp_path)


@pytest.mark.parametrize("module_name", ["brains.openclaw", "brains.api"])
def test_session_entry_points_exist_for_composition_root(module_name: str) -> None:
    """core/cli.py resolves brains.{name}.run_cabinet_session dynamically."""
    import importlib

    module = importlib.import_module(module_name)
    assert callable(module.run_cabinet_session)
    assert callable(module.get_brain)
