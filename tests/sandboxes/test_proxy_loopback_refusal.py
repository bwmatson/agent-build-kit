"""The allowlisting proxy says why it refuses a loopback host (spec: agent-test-commands): a
local address is not reachable from the sandbox, a test that starts a local server cannot pass
there, and the pipeline runs it outside the sandbox. Any other refused host keeps its text, and
the report of a refused host is the same for both."""

from __future__ import annotations

import pytest

from agent_build_kit.sandboxes.proxy import Proxy
from tests.sandboxes.proxy_support import UPSTREAM_BODY, connect, plain_get, send_raw, upstream

OTHER_HOST_TEXT = "sandbox: the host example.com is not on the allowed list"


@pytest.mark.parametrize("url", ["http://127.0.0.1:8123/", "http://localhost:8123/"])
def test_a_refused_loopback_request_says_why(url: str) -> None:
    with Proxy(["pypi.org"]) as proxy:
        code, body = plain_get(proxy.port, url)

    assert code == 403
    assert "local address" in body
    assert "not reachable from the sandbox" in body
    assert "cannot pass" in body
    assert "outside the sandbox" in body


@pytest.mark.parametrize(
    "target",
    [
        "127.0.0.1:8123",
        "localhost:8123",
        "LOCALHOST.:8123",
        "app.localhost:8123",
        "[::1]:8123",
        "[::ffff:127.0.0.1]:8123",
    ],
)
def test_a_refused_loopback_connect_says_why(target: str) -> None:
    with Proxy(["pypi.org"]) as proxy:
        code, body = connect(proxy.port, target)

    assert code == 403
    assert "not reachable from the sandbox" in body


def test_a_refused_host_that_is_not_loopback_keeps_its_text() -> None:
    with Proxy(["pypi.org"]) as proxy:
        code, body = plain_get(proxy.port, "http://example.com/")

    assert code == 403
    assert body.strip() == OTHER_HOST_TEXT


@pytest.mark.parametrize(
    ("target", "reported"),
    [("127.0.0.1:8123", ("127.0.0.1", 8123)), ("localhost:8123", ("localhost", 8123))],
)
def test_a_refused_loopback_host_is_still_reported_with_its_port(
    target: str, reported: tuple[str, int]
) -> None:
    refused: list[tuple[str, int]] = []

    with Proxy(["pypi.org"], on_refused=lambda host, port: refused.append((host, port))) as proxy:
        connect(proxy.port, target)

    assert refused == [reported]


@pytest.mark.parametrize("target", ["example.com:8123", "0.0.0.0:8123", "localhost.example.com:80"])
def test_a_host_that_is_not_loopback_gets_the_plain_text(target: str) -> None:
    with Proxy(["pypi.org"]) as proxy:
        code, body = connect(proxy.port, target)

    assert code == 403
    assert "not on the allowed list" in body
    assert "not reachable from the sandbox" not in body


def test_an_allowed_loopback_host_still_connects() -> None:
    with upstream() as port, Proxy(["127.0.0.1"]) as proxy:
        code, body = plain_get(proxy.port, f"http://127.0.0.1:{port}/")

    assert code == 200
    assert body == UPSTREAM_BODY


def test_a_raw_request_for_a_loopback_host_is_answered_with_the_text() -> None:
    with Proxy(["pypi.org"]) as proxy:
        code, rest = send_raw(
            proxy.port, "GET http://127.0.0.1:8123/ HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
        )

    assert code == 403
    assert "not reachable from the sandbox" in rest
