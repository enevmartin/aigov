"""The ONLY way aigov talks to the outside world (чл. 5, чл. 8).

:class:`PoliteClient` enforces, in code, for every request and every
redirect hop:

- a fixed, identifiable User-Agent with a contact address (``bot@aigov.bg``);
- ``robots.txt`` is fetched once per host BEFORE the first request to it and
  honoured: a disallowed path is never requested (:class:`RobotsDenied`);
  a 4xx ``robots.txt`` means "no rules", a 5xx or network error means
  "disallow everything" (RFC 9309 §2.3.1);
- per-host spacing of ``max(Crawl-delay, floor)`` seconds, the floor being
  at least 1.5 s — the robots.txt request itself is spaced the same way.

Nothing is written to disk: callers get bytes in memory, parse them and keep
only aggregates (чл. 1.6).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "aigov.bg-bot/1.0 (+https://aigov.bg; bot@aigov.bg)"
ROBOTS_AGENT = "aigov.bg-bot"
MIN_FLOOR = 1.5  # чл. 5 — never below this, whatever the caller asks
DEFAULT_FLOOR = 2.0
MAX_REDIRECTS = 5


class RobotsDenied(PermissionError):
    """robots.txt forbids the URL for our agent — the request was NOT sent."""


@dataclass
class _HostPolicy:
    parser: RobotFileParser | None  # None = allow all (robots 4xx)
    deny_all: bool = False
    delay: float = DEFAULT_FLOOR
    last: float | None = None


@dataclass
class RequestLog:
    """One line per request actually sent (evidence for audits)."""

    entries: list[dict[str, object]] = field(default_factory=list)


class PoliteClient:
    """httpx wrapper that cannot be impolite. Inject *transport*/*clock* in tests."""

    def __init__(
        self,
        floor: float = DEFAULT_FLOOR,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.floor = max(floor, MIN_FLOOR)
        self._clock = clock
        self._sleep = sleep
        self._hosts: dict[str, _HostPolicy] = {}
        self._robots_last: dict[str, float] = {}  # robots.txt fetch time per host
        self.log = RequestLog()
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=False,  # every hop goes through robots + throttle
            transport=transport,
        )

    # -- public API -------------------------------------------------------
    def get(self, url: str) -> httpx.Response:
        """GET *url*, following redirects politely; raises on HTTP errors."""
        for _ in range(MAX_REDIRECTS + 1):
            response = self._send(url)
            if response.is_redirect and "location" in response.headers:
                url = urljoin(url, response.headers["location"])
                continue
            response.raise_for_status()
            return response
        raise httpx.TooManyRedirects(f"more than {MAX_REDIRECTS} redirects: {url}")

    def fetch(self, url: str) -> httpx.Response:
        """Alias with the ScraperBase shape (used by the RSS collector)."""
        return self.get(url)

    def allowed(self, url: str) -> bool:
        """Whether robots.txt lets us fetch *url* (fetches robots.txt once)."""
        policy = self._policy(url)
        if policy.deny_all:
            return False
        return policy.parser is None or policy.parser.can_fetch(ROBOTS_AGENT, url)

    def crawl_delay(self, url: str) -> float:
        return self._policy(url).delay

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # -- internals --------------------------------------------------------
    def _send(self, url: str) -> httpx.Response:
        if not self.allowed(url):
            self.log.entries.append({"url": url, "status": "robots-denied"})
            raise RobotsDenied(f"robots.txt disallows {url}")
        return self._throttled(url)

    def _throttled(self, url: str) -> httpx.Response:
        host = _host(url)
        policy = self._hosts.get(host)
        delay = policy.delay if policy else self.floor
        last = policy.last if policy else self._robots_last.get(host)
        if last is not None:
            wait = delay - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        response = self._client.get(url)
        now = self._clock()
        if policy:
            policy.last = now
        else:
            self._robots_last[host] = now
        self.log.entries.append({"url": url, "status": response.status_code, "t": now})
        return response

    def _policy(self, url: str) -> _HostPolicy:
        host = _host(url)
        if host in self._hosts:
            return self._hosts[host]
        parts = urlsplit(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        status, text, ctype = 599, "", ""
        try:
            response = self._throttled(robots_url)
            status, text = response.status_code, response.text
            ctype = response.headers.get("content-type", "")
        except httpx.HTTPError:
            pass  # unreachable robots.txt -> treated as 5xx: disallow all
        if status >= 500:
            policy = _HostPolicy(parser=None, deny_all=True, delay=self.floor)
        elif status >= 400 or "html" in ctype:  # 4xx / soft-404 page = no rules
            policy = _HostPolicy(parser=None, delay=self.floor)  # no rules
        else:
            parser = RobotFileParser()
            parser.parse(text.splitlines())
            declared = parser.crawl_delay(ROBOTS_AGENT)
            policy = _HostPolicy(parser=parser, delay=max(self.floor, float(declared or 0)))
        policy.last = self._robots_last.get(host)
        self._hosts[host] = policy
        return policy


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower()
