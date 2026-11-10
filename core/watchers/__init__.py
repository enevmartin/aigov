"""Tier-2 watchers: official documents -> event_analysis tasks (чл. 8).

``watchers.yaml`` declares official feeds (Народно събрание, Държавен вестник,
strategy.bg, Министерски съвет, МФ). A new item whose title matches a
ministry's routing keywords is fetched (through the polite client), reduced
to plain text with a sha256, and handed to that ministry as an
``event_analysis`` task TOGETHER WITH its tier-1 indicators. The document
text lives only inside the task (deleted after publish, чл. 1.6); the
publication keeps url + sha256.
"""

from core.watchers.watch import (
    Document,
    WatcherRegistry,
    WatcherSpec,
    enqueue_event_analysis,
    fetch_document,
    load_watchers,
    route,
    scan,
)

__all__ = [
    "Document",
    "WatcherRegistry",
    "WatcherSpec",
    "enqueue_event_analysis",
    "fetch_document",
    "load_watchers",
    "route",
    "scan",
]
