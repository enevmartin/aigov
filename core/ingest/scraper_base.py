"""Polite HTTP fetching shared by all collectors.

Every outbound request in the system goes through :class:`ScraperBase`:
rate-limited (default 1.5 s between requests), identified by an honest
User-Agent, with sane timeouts. Subclasses implement site-specific parsing;
this base owns transport only.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable

import httpx

DEFAULT_USER_AGENT = (
    "aigov.bg data collector (+https://aigov.bg; contact: admin@aigov.bg)"
)
DEFAULT_MIN_INTERVAL = 1.5  # seconds between requests, per collector instance
DEFAULT_TIMEOUT = 30.0


def user_agent() -> str:
    """The User-Agent for all requests (overridable via AIGOV_USER_AGENT)."""
    return os.environ.get("AIGOV_USER_AGENT", DEFAULT_USER_AGENT)


class RateLimiter:
    """Enforce a minimum interval between calls.

    Clock and sleep are injectable so tests run instantly.
    """

    def __init__(
        self,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        """Block until at least ``min_interval`` has passed since the last call."""
        now = self._clock()
        if self._last is not None:
            remaining = self.min_interval - (now - self._last)
            if remaining > 0:
                self._sleep(remaining)
                now = self._clock()
        self._last = now


class ScraperBase:
    """Rate-limited, politely identified HTTP client for collectors."""

    def __init__(
        self,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Create the client.

        *transport* is injectable (httpx.MockTransport) so tests never touch
        the network.
        """
        self.limiter = RateLimiter(min_interval)
        self._client = httpx.Client(
            headers={"User-Agent": user_agent()},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )

    def fetch(self, url: str) -> httpx.Response:
        """GET *url* respecting the rate limit; raises on HTTP errors."""
        self.limiter.wait()
        response = self._client.get(url)
        response.raise_for_status()
        return response

    def close(self) -> None:
        """Release the underlying connection pool."""
        self._client.close()

    def __enter__(self) -> ScraperBase:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
