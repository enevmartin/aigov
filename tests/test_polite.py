"""The polite client: robots.txt, Crawl-delay and spacing enforced in code."""

from __future__ import annotations

import httpx
import pytest

from core.net import USER_AGENT, PoliteClient, RobotsDenied


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def make(
    robots: dict[str, tuple[int, str]], seen: list[httpx.Request]
) -> tuple[PoliteClient, FakeClock]:
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        host = request.url.host
        if request.url.path == "/robots.txt":
            status, body = robots.get(host, (404, ""))
            return httpx.Response(status, text=body, headers={"content-type": "text/plain"})
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return httpx.Response(200, text="ok")

    client = PoliteClient(transport=httpx.MockTransport(handler), clock=clock, sleep=clock.sleep)
    return client, clock


def test_user_agent_has_bot_contact() -> None:
    seen: list[httpx.Request] = []
    client, _ = make({}, seen)
    client.get("https://a.bg/x")
    assert USER_AGENT.endswith("bot@aigov.bg)")
    assert all(r.headers["user-agent"] == USER_AGENT for r in seen)


def test_disallowed_path_is_never_requested() -> None:
    seen: list[httpx.Request] = []
    client, _ = make({"a.bg": (200, "User-agent: *\nDisallow: /secret\n")}, seen)
    with pytest.raises(RobotsDenied):
        client.get("https://a.bg/secret/data.csv")
    assert [r.url.path for r in seen] == ["/robots.txt"]


def test_robots_5xx_means_disallow_all() -> None:
    seen: list[httpx.Request] = []
    client, _ = make({"a.bg": (503, "")}, seen)
    with pytest.raises(RobotsDenied):
        client.get("https://a.bg/data")
    assert [r.url.path for r in seen] == ["/robots.txt"]


def test_robots_404_means_allow() -> None:
    seen: list[httpx.Request] = []
    client, _ = make({}, seen)
    assert client.get("https://a.bg/data").text == "ok"


def test_crawl_delay_is_honoured_between_requests() -> None:
    seen: list[httpx.Request] = []
    client, clock = make({"a.bg": (200, "User-agent: *\nCrawl-delay: 10\n")}, seen)
    client.get("https://a.bg/1")
    client.get("https://a.bg/2")
    times = [e["t"] for e in client.log.entries]
    assert all(b - a >= 10 for a, b in zip(times, times[1:], strict=False))  # type: ignore[operator]


def test_floor_spacing_applies_to_robots_and_cannot_go_below_1_5s() -> None:
    seen: list[httpx.Request] = []
    clock = FakeClock()
    client = PoliteClient(
        floor=0.1,
        transport=httpx.MockTransport(lambda r: (seen.append(r), httpx.Response(404))[1]),
        clock=clock,
        sleep=clock.sleep,
    )
    assert client.floor == 1.5
    with pytest.raises(httpx.HTTPStatusError):
        client.get("https://a.bg/x")  # robots 404 -> allowed; page 404 -> error
    times = [e["t"] for e in client.log.entries]
    assert times[1] - times[0] >= 1.5  # type: ignore[operator]


def test_redirect_hop_is_checked_and_throttled() -> None:
    seen: list[httpx.Request] = []
    client, _ = make({"a.bg": (200, "User-agent: *\nDisallow: /new\n")}, seen)
    with pytest.raises(RobotsDenied):
        client.get("https://a.bg/old")  # /old allowed, but redirects to disallowed /new
    assert [r.url.path for r in seen] == ["/robots.txt", "/old"]


def test_hosts_are_spaced_independently() -> None:
    seen: list[httpx.Request] = []
    client, clock = make({}, seen)
    client.get("https://a.bg/1")
    slept_before = sum(clock.slept)
    client.get("https://b.bg/1")  # new host: only its own robots spacing applies
    client.get("https://a.bg/2")
    a_times = [e["t"] for e in client.log.entries if "a.bg" in str(e["url"])]
    assert a_times[-1] - a_times[-2] >= 2.0  # type: ignore[operator]
    assert slept_before >= 2.0  # robots.txt -> first page on a.bg was spaced too
