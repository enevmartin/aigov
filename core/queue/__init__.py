"""File-based task queue: ``tasks/{pending,running,done,failed}``.

State transitions are atomic directory renames — no locks, no databases.
Any brain process can safely claim a task; a crashed run leaves its task in
``running/`` where ``requeue_stale()`` can recover it.
"""

from core.queue.filequeue import FileQueue, QueueState

__all__ = ["FileQueue", "QueueState"]
