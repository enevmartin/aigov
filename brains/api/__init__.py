"""api brain — SKELETON, not implemented.

Direct LLM API adapter (DeepSeek/Kimi planned). See README.md here.
Selecting ``brain: api`` in config.yaml today fails loudly at session start.
"""

from brains.api.adapter import ApiBrain, get_brain, run_cabinet_session

__all__ = ["ApiBrain", "get_brain", "run_cabinet_session"]
