"""Publishing gate: validate brain output and release it to ``published/``.

The only path from a brain's ``output/`` to the public site. Invalid output
goes to ``failed/`` with a recorded reason — it never becomes public.
"""

from core.publish.publisher import (
    cabinet_roster,
    ministry_names,
    publish_all,
    rebuild_index,
    validate_output,
)

__all__ = [
    "cabinet_roster",
    "ministry_names",
    "publish_all",
    "rebuild_index",
    "validate_output",
]
