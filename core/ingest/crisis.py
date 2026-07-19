"""Crisis detection: deterministic keyword-spike scan over collected news.

Pure Python, no LLM (чл. 7 — detections and triggers are deterministic core
code; the LLM is called only for the analysis itself). A ministry opts in by
declaring in its ``ministry.yaml``::

    crisis_keywords:
      min_hits: 3          # a keyword must appear in this many distinct items
      keywords:
        - фалит
        - дефицит

When a spike is detected the CLI enqueues a ``crisis_brief`` task whose input
carries the matched items and the trigger metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CrisisTrigger:
    """The result of a positive spike detection."""

    keywords: list[str]
    counts: dict[str, int] = field(default_factory=dict)


def detect_spike(
    texts: list[str], keywords: list[str], min_hits: int = 3
) -> CrisisTrigger | None:
    """Return a trigger if any keyword appears in >= *min_hits* distinct texts.

    Matching is case-insensitive substring search per text (an item mentioning
    a keyword five times still counts once — spikes are about breadth of
    coverage, not repetition inside one article).
    """
    if not keywords or min_hits < 1:
        return None
    lowered = [text.lower() for text in texts]
    counts: dict[str, int] = {}
    for keyword in keywords:
        needle = keyword.lower().strip()
        if not needle:
            continue
        hits = sum(1 for text in lowered if needle in text)
        if hits >= min_hits:
            counts[keyword] = hits
    if not counts:
        return None
    return CrisisTrigger(keywords=sorted(counts), counts=counts)
