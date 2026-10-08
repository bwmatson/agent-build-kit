"""`abk serve` listens on the loopback address only (spec: web-ui)."""

from __future__ import annotations

import argparse
import socket

import httpx
import pytest

from agent_build_kit.cli.serve_cmd import cmd_serve
from agent_build_kit.installation import Installation
from agent_build_kit.serve.server import start_server


def other_address() -> str | None:
    """An address of this host that is not loopback, or None where it has none."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        address = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    return None if address.startswith("127.") else address


def test_the_server_binds_the_loopback_address(inst: Installation) -> None:
    with start_server(inst) as server:
        assert server.host == "127.0.0.1"
        assert server.url.startswith("http://127.0.0.1:")
        assert httpx.get(f"{server.url}/api/pipeline").status_code == 200


def test_a_request_through_another_address_of_the_host_is_refused(inst: Installation) -> None:
    address = other_address()
    if address is None:
        pytest.skip("this host has no address besides loopback")

    with start_server(inst) as server, pytest.raises(httpx.TransportError):
        httpx.get(f"http://{address}:{server.port}/api/pipeline", timeout=2)


def test_the_server_stops_listening_when_it_is_stopped(inst: Installation) -> None:
    with start_server(inst) as server:
        url = server.url

    with pytest.raises(httpx.TransportError):
        httpx.get(f"{url}/api/pipeline", timeout=2)


def test_a_port_already_in_use_is_reported_by_name_with_a_failing_exit(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    with start_server(inst) as server:
        port = server.port
        code = cmd_serve(argparse.Namespace(port=port), inst)

    assert code != 0
    out = capsys.readouterr().out
    assert str(port) in out
    assert "--port" in out
