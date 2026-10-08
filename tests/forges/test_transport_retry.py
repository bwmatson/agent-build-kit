"""The transport's timeout rule and its refusal to retry, against a mock host: it raises on
the first failure and the layer above the forges decides what to repeat."""

from __future__ import annotations

import time

import httpx
import pytest

from agent_build_kit.forges.transport import (
    AuthError,
    Credentials,
    HostError,
    RateLimited,
    Transport,
)
from agent_build_kit.settings import settings
from tests.forges.mock_host import MockHost, ok, recorded

CREDENTIALS = Credentials(scheme="Bearer", token="tok-example", source="setting", owner="example")


def transport(host: MockHost) -> Transport:
    return Transport("https://api.example.test", CREDENTIALS, transport=host, timeout=7.0)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The transport does not wait: the retry layer above the forges does."""
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    return slept


def test_a_503_is_raised_on_the_first_answer(no_waiting: list[float]) -> None:
    host = MockHost(httpx.Response(503, headers={"retry-after": "3"}), ok({"id": 1}))

    with pytest.raises(HostError) as caught:
        transport(host).request("GET", "/repos/example/app")

    assert caught.value.retry_after == 3
    assert len(host.requests) == 1
    assert no_waiting == []


def test_a_timeout_on_a_read_is_raised_typed_without_a_second_call() -> None:
    host = MockHost(httpx.ReadTimeout("timed out"))

    with pytest.raises(HostError):
        transport(host).request("GET", "/repos/example/app")

    assert len(host.requests) == 1


@pytest.mark.parametrize(
    "answer, hint",
    [("rate_limit_secondary_403", 60), ("rate_limit_429", 30)],
)
def test_a_rate_limit_is_raised_with_its_hint_and_not_waited_for(
    answer: str, hint: int, no_waiting: list[float]
) -> None:
    host = MockHost(recorded(answer))

    with pytest.raises(RateLimited) as caught:
        transport(host).request("GET", "/repos/example/app")

    assert caught.value.retry_after == hint
    assert len(host.requests) == 1
    assert no_waiting == []


def test_a_primary_rate_limit_403_takes_its_hint_from_the_reset_time() -> None:
    reset = str(int(time.time()) + 30)
    host = MockHost(recorded("rate_limit_primary_403", **{"x-ratelimit-reset": reset}))

    with pytest.raises(RateLimited) as caught:
        transport(host).request("GET", "/repos/example/app")

    assert caught.value.retry_after is not None and 25 <= caught.value.retry_after <= 30
    assert len(host.requests) == 1


def test_a_plain_403_is_a_refusal_not_a_rate_limit() -> None:
    host = MockHost(recorded("bad_credentials_403"))

    with pytest.raises(AuthError):
        transport(host).request("GET", "/repos/example/app")

    assert len(host.requests) == 1


def test_a_hint_beyond_the_ceiling_is_carried_on_the_error() -> None:
    host = MockHost(httpx.Response(503, headers={"retry-after": "3600"}))

    with pytest.raises(HostError) as caught:
        transport(host).request("GET", "/repos/example/app")

    assert caught.value.retry_after == 3600
    assert len(host.requests) == 1


def test_a_timeout_applies_to_every_call() -> None:
    host = MockHost(ok({}))
    t = transport(host)

    t.request("GET", "/a")
    t.request("PUT", "/b", json={"x": 1})

    assert len(host.requests) == 2
    for request in host.requests:
        timeout = request.extensions["timeout"]
        assert timeout["read"] == 7.0 and timeout["connect"] == 7.0


def test_the_timeout_defaults_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "forge_timeout_seconds", 11.0)
    host = MockHost(ok({}))

    Transport("https://api.example.test", CREDENTIALS, transport=host).request("GET", "/a")

    assert host.requests[0].extensions["timeout"]["read"] == 11.0


def test_the_credential_is_sent_as_the_authorization_header() -> None:
    host = MockHost(ok({}))

    transport(host).request("GET", "/a")

    assert host.requests[0].headers["authorization"] == "Bearer tok-example"


def test_a_closed_transport_makes_no_more_calls() -> None:
    host = MockHost(ok({}))
    with transport(host) as t:
        t.request("GET", "/a")

    with pytest.raises(RuntimeError):
        t.request("GET", "/a")
