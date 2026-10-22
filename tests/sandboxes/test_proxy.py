"""The allowlisting proxy: what it passes, what it refuses and how it points a step at itself."""

from __future__ import annotations

import socket
import struct
import threading

import pytest

from agent_build_kit.sandboxes.policy import proxy_environment
from agent_build_kit.sandboxes.proxy import Proxy, host_allowed
from tests.sandboxes.proxy_support import UPSTREAM_BODY, connect, plain_get, send_raw, upstream

GET_THROUGH_TUNNEL = "GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"


def test_plain_http_to_an_allowed_host_is_passed() -> None:
    with upstream() as port, Proxy(["127.0.0.1"]) as proxy:
        code, body = plain_get(proxy.port, f"http://127.0.0.1:{port}/")

    assert code == 200
    assert body == UPSTREAM_BODY


def test_connect_to_an_allowed_host_opens_a_tunnel() -> None:
    with upstream() as port, Proxy(["127.0.0.1"]) as proxy:
        code, body = connect(proxy.port, f"127.0.0.1:{port}", then=GET_THROUGH_TUNNEL)

    assert code == 200
    assert UPSTREAM_BODY in body


def test_plain_http_to_another_host_is_refused_naming_it() -> None:
    with Proxy(["pypi.org"]) as proxy:
        code, body = plain_get(proxy.port, "http://example.com/")

    assert code == 403
    assert "example.com" in body


def test_connect_to_another_host_is_refused_naming_it() -> None:
    with Proxy(["pypi.org"]) as proxy:
        code, body = connect(proxy.port, "example.com:443")

    assert code == 403
    assert "example.com" in body


@pytest.mark.parametrize("host", ["a.example.test", "x.a.example.test", "A.Example.Test."])
def test_a_suffix_pattern_matches_a_subdomain(host: str) -> None:
    assert host_allowed(host, ["*.example.test"])


@pytest.mark.parametrize("host", ["example.test", "badexample.test", "example.org"])
def test_a_suffix_pattern_does_not_match_the_rest(host: str) -> None:
    assert not host_allowed(host, ["*.example.test"])


def test_a_post_body_sent_with_its_headers_reaches_the_upstream() -> None:
    request = "POST {url} HTTP/1.1\r\nHost: x\r\nContent-Length: 4\r\nConnection: close\r\n\r\nping"
    with upstream() as port, Proxy(["127.0.0.1"]) as proxy:
        code, body = send_raw(proxy.port, request.format(url=f"http://127.0.0.1:{port}/"))

    assert code == 200
    assert body == "ping"


def test_tunnel_bytes_sent_with_the_connect_reach_the_upstream() -> None:
    with upstream() as port, Proxy(["127.0.0.1"]) as proxy:
        target = f"127.0.0.1:{port}"
        code, body = send_raw(
            proxy.port, f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n{GET_THROUGH_TUNNEL}"
        )

    assert code == 200
    assert UPSTREAM_BODY in body


def test_a_second_request_on_the_connection_is_not_sent_to_the_first_host() -> None:
    first = "GET http://127.0.0.1:{port}/ HTTP/1.1\r\nHost: x\r\nConnection: keep-alive\r\n\r\n"
    second = "GET http://other.example.test/ HTTP/1.1\r\nHost: other.example.test\r\n\r\n"
    with upstream() as port, Proxy(["127.0.0.1"]) as proxy:
        code, body = send_raw(proxy.port, first.format(port=port) + second)

    assert code == 200
    assert body == UPSTREAM_BODY  # the answer to the first request only, then the close


def test_a_suffix_pattern_does_not_allow_a_name_that_only_ends_alike() -> None:
    with Proxy(["*.example.test"]) as proxy:
        refused, body = connect(proxy.port, "badexample.test:443")

    assert refused == 403
    assert "badexample.test" in body


def test_a_connection_reset_by_the_client_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    thread_errors: list[object] = []
    monkeypatch.setattr(threading, "excepthook", thread_errors.append)

    with upstream() as port, Proxy(["127.0.0.1"]) as proxy:
        client = socket.create_connection(("127.0.0.1", proxy.port), timeout=10)
        client.sendall(b"CONNECT 127.0.0.1:")
        client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        client.close()  # a reset, not a close

        code, body = plain_get(proxy.port, f"http://127.0.0.1:{port}/")

    # Leaving `Proxy` joined every handler, the one that took the reset included.
    assert code == 200
    assert body == UPSTREAM_BODY
    assert thread_errors == []
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_the_environment_points_both_spellings_at_the_proxy(scheme: str) -> None:
    environment = proxy_environment(8123)

    assert environment[f"{scheme.upper()}_PROXY"] == "http://127.0.0.1:8123"
    assert environment[f"{scheme}_proxy"] == "http://127.0.0.1:8123"
