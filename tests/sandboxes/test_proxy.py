"""The allowlisting proxy: what it passes, what it refuses and how it points a step at itself."""

from __future__ import annotations

import socket
import struct
import threading

import pytest

from agent_build_kit.sandboxes.policy import proxy_environment
from agent_build_kit.sandboxes.proxy import Proxy
from tests.sandboxes.proxy_support import UPSTREAM_BODY, connect, plain_get, upstream

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


def test_a_suffix_pattern_allows_a_subdomain_and_refuses_the_rest() -> None:
    with Proxy(["*.example.test"]) as proxy:
        allowed, _ = connect(proxy.port, "a.example.test:443")
        refused, body = connect(proxy.port, "example.org:443")

    # The allowed name does not resolve here, so the proxy fails to reach it; that is not a refusal.
    assert allowed != 403
    assert refused == 403
    assert "example.org" in body


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

    assert code == 200
    assert body == UPSTREAM_BODY
    assert thread_errors == []
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_the_environment_points_both_spellings_at_the_proxy(scheme: str) -> None:
    environment = proxy_environment(8123)

    assert environment[f"{scheme.upper()}_PROXY"] == "http://127.0.0.1:8123"
    assert environment[f"{scheme}_proxy"] == "http://127.0.0.1:8123"
