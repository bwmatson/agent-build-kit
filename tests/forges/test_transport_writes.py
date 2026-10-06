"""Which writes the transport may repeat."""

from __future__ import annotations

import httpx
import pytest

from agent_build_kit.forges.transport import Credentials, HostError, Transport
from tests.forges.mock_host import MockHost, ok

CREDENTIALS = Credentials(scheme="Bearer", token="tok-example", source="setting", owner="example")
COMMENTS = "/repos/example/app/issues/1/comments"


def transport(host: MockHost) -> Transport:
    return Transport(
        "https://api.example.test",
        CREDENTIALS,
        transport=host,
        timeout=7.0,
        retries=2,
        sleep=lambda _: None,
    )


def test_a_create_that_times_out_is_not_retried() -> None:
    host = MockHost(httpx.ReadTimeout("timed out"))

    with pytest.raises(HostError):
        transport(host).request("POST", COMMENTS, json={"body": "x"})

    assert len(host.requests) == 1


def test_a_create_answered_503_is_not_retried() -> None:
    host = MockHost(httpx.Response(503), ok({"id": 5}, 201))

    with pytest.raises(HostError):
        transport(host).request("POST", COMMENTS, json={"body": "x"})

    assert len(host.requests) == 1


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_an_idempotent_write_is_retried(method: str) -> None:
    host = MockHost(httpx.ReadTimeout("timed out"), ok({}))

    transport(host).request(method, "/repos/example/app/labels/x")

    assert len(host.requests) == 2


def test_a_post_the_caller_marks_safe_is_retried() -> None:
    host = MockHost(httpx.ReadTimeout("timed out"), ok({"id": 5}, 201))

    transport(host).request("POST", "/repos/example/app/dispatches", json={}, idempotent=True)

    assert len(host.requests) == 2
