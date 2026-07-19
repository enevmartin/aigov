"""openclaw brain — SKELETON, not implemented.

See README.md in this directory for how it will plug in. Selecting
``brain: openclaw`` in config.yaml today fails loudly at session start.
"""

from brains.openclaw.adapter import OpenClawBrain, get_brain, run_cabinet_session

__all__ = ["OpenClawBrain", "get_brain", "run_cabinet_session"]
