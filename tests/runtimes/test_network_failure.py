"""Reading a failed run's words for a network outage.

A name that cannot be resolved or a route that does not exist is a strong sign: the run
itself saw the network fail. A refused or timed-out connection is weak, because a live
network produces both. A failure that carries an HTTP status is an answer from a
reachable service, so it is never matched, whatever words ride along with it.
"""

from __future__ import annotations

import pytest

from agent_build_kit.runtimes.network import network_failure


@pytest.mark.parametrize(
    "text",
    [
        "API Error: Can't reach the API server — check your internet or DNS (EAI_AGAIN)",
        "getaddrinfo ENOTFOUND api.example.test",
        "connect ENETUNREACH 192.0.2.7:443",
        "connect EHOSTUNREACH 192.0.2.7:443",
        "curl: (6) Temporary failure in name resolution",
    ],
)
def test_a_name_or_route_that_cannot_be_reached_is_a_strong_sign(text: str) -> None:
    assert network_failure(text) == "strong"


@pytest.mark.parametrize(
    "text",
    [
        "API Error: Can't reach the API server",
        "connect ECONNREFUSED 192.0.2.7:443",
        "the request failed: connect timed out",
    ],
)
def test_a_failure_a_live_network_can_also_produce_is_a_weak_sign(text: str) -> None:
    assert network_failure(text) == "weak"


@pytest.mark.parametrize(
    "text",
    [
        "API Error: 429 rate_limit_error",
        "API Error: 500 Internal server error",
        "API Error: 529 overloaded_error",
        "Claude AI usage limit reached|1919763200",
        "I can't help with that request.",
        "API Error: 503 upstream connect error: ECONNREFUSED",
        "API Error: 500 getaddrinfo EAI_AGAIN db.internal",
        "",
    ],
)
def test_an_answer_from_a_reachable_service_is_not_a_sign(text: str) -> None:
    assert network_failure(text) is None
