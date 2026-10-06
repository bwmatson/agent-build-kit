"""The transport's retry and timeout rules, against a mock host."""

from __future__ import annotations

import time

import httpx
import pytest

from agent_build_kit.forges.transport import (
    MAX_DELAY,
    AuthError,
    Credentials,
    HostError,
    RateLimited,
    Transport,
)
from agent_build_kit.settings import settings
from tests.forges.mock_host import MockHost, ok, recorded

CREDENTIALS = Credentials(scheme="Bearer", token="tok-example", source="setting", owner="example")


def transport(host: MockHost, sleeps: list[float], *, retries: int = 2) -> Transport:
    return Transport(
        "https://api.example.test",
        CREDENTIALS,
        transport=host,
        timeout=7.0,
        retries=retries,
        sleep=sleeps.append,
    )


def test_a_503_then_a_200_succeeds_on_retry_honouring_retry_after() -> None:
    host = MockHost(httpx.Response(503, headers={"retry-after": "3"}), ok({"id": 1}))
    sleeps: list[float] = []

    response = transport(host, sleeps).request("GET", "/repos/example/app")

    assert response.data == {"id": 1}
    assert len(host.requests) == 2
    assert sleeps and sleeps[0] >= 3


def test_a_host_that_stays_down_fails_after_the_bound_with_a_typed_error() -> None:
    host = MockHost(httpx.Response(503))

    with pytest.raises(HostError):
        transport(host, []).request("GET", "/repos/example/app")

    assert len(host.requests) == 3  # the first attempt and two retries


def test_a_timeout_is_retried_for_a_read_then_fails_typed() -> None:
    host = MockHost(httpx.ReadTimeout("timed out"))

    with pytest.raises(HostError):
        transport(host, []).request("GET", "/repos/example/app")

    assert len(host.requests) == 3


def test_a_rate_limit_that_persists_carries_the_hint() -> None:
    host = MockHost(httpx.Response(429, headers={"retry-after": "9"}))

    with pytest.raises(RateLimited) as caught:
        transport(host, []).request("GET", "/repos/example/app")

    assert caught.value.retry_after == 9
    assert len(host.requests) == 3


def test_a_timeout_applies_to_every_call() -> None:
    host = MockHost(ok({}))
    t = transport(host, [])

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

    transport(host, []).request("GET", "/a")

    assert host.requests[0].headers["authorization"] == "Bearer tok-example"


@pytest.mark.parametrize(
    "answer, hint",
    [("rate_limit_secondary_403", 60), ("rate_limit_429", 30)],
)
def test_a_rate_limit_with_retry_after_is_retried_then_typed(answer: str, hint: int) -> None:
    host = MockHost(recorded(answer))
    sleeps: list[float] = []

    with pytest.raises(RateLimited) as caught:
        transport(host, sleeps).request("GET", "/repos/example/app")

    assert caught.value.retry_after == hint
    assert len(host.requests) == 3
    assert all(s >= hint for s in sleeps)


def test_a_primary_rate_limit_403_takes_its_hint_from_the_reset_time() -> None:
    reset = str(int(time.time()) + 30)
    host = MockHost(recorded("rate_limit_primary_403", **{"x-ratelimit-reset": reset}))
    sleeps: list[float] = []

    with pytest.raises(RateLimited) as caught:
        transport(host, sleeps).request("GET", "/repos/example/app")

    assert caught.value.retry_after is not None and 25 <= caught.value.retry_after <= 30
    assert len(host.requests) == 3
    assert all(s >= 25 for s in sleeps)


def test_a_rate_limit_then_a_200_succeeds_on_retry() -> None:
    host = MockHost(recorded("rate_limit_primary_403", **{"x-ratelimit-reset": "0"}), ok({"id": 1}))

    response = transport(host, []).request("GET", "/repos/example/app")

    assert response.data == {"id": 1}
    assert len(host.requests) == 2


def test_a_plain_403_is_a_refusal_not_a_rate_limit() -> None:
    host = MockHost(recorded("bad_credentials_403"))

    with pytest.raises(AuthError):
        transport(host, []).request("GET", "/repos/example/app")

    assert len(host.requests) == 1


def test_a_429_hint_beyond_the_ceiling_fails_at_once_instead_of_sleeping() -> None:
    host = MockHost(httpx.Response(429, headers={"retry-after": "3600"}))
    sleeps: list[float] = []

    with pytest.raises(RateLimited) as caught:
        transport(host, sleeps).request("GET", "/repos/example/app")

    assert caught.value.retry_after == 3600
    assert len(host.requests) == 1
    assert all(s <= MAX_DELAY for s in sleeps)


def test_a_503_hint_beyond_the_ceiling_fails_at_once_instead_of_sleeping() -> None:
    host = MockHost(httpx.Response(503, headers={"retry-after": "3600"}))
    sleeps: list[float] = []

    with pytest.raises(HostError) as caught:
        transport(host, sleeps).request("GET", "/repos/example/app")

    assert caught.value.retry_after == 3600
    assert len(host.requests) == 1
    assert all(s <= MAX_DELAY for s in sleeps)


def test_a_closed_transport_makes_no_more_calls() -> None:
    host = MockHost(ok({}))
    with transport(host, []) as t:
        t.request("GET", "/a")

    with pytest.raises(RuntimeError):
        t.request("GET", "/a")
