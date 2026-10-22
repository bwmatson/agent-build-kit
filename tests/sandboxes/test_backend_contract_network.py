"""What every real sandbox backend promises about the network, with the real restrictions.

A confined process reaches the proxy's port and nothing else. Skipped where the kernel cannot
confine the network, with the reason. The file-write promises are in `test_backend_contract.py`.
"""

from __future__ import annotations

import os
import socket
import sys
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from agent_build_kit.sandboxes import SandboxBackend
from agent_build_kit.sandboxes.policy import proxy_environment
from agent_build_kit.sandboxes.proxy import Proxy
from tests.sandboxes.landlock_support import Scene, require_network_rules, run_confined
from tests.sandboxes.proxy_support import UPSTREAM_BODY, upstream

CONNECT = (
    "import socket, sys\n"
    "try:\n"
    "    socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=5).close()\n"
    "    print('connected')\n"
    "except OSError as failure:\n"
    "    print(type(failure).__name__)\n"
)

FETCH = (
    "import sys, urllib.error, urllib.request\n"
    "try:\n"
    "    print(urllib.request.urlopen(sys.argv[1], timeout=10).read().decode())\n"
    "except urllib.error.HTTPError as failure:\n"
    "    print(failure.code, failure.read().decode())\n"
)


@contextmanager
def listening(host: str) -> Iterator[int]:
    """A listening local socket on `host`, so a refused connection is the sandbox's doing and not
    an absent server's."""
    with socket.socket() as server:
        server.bind((host, 0))
        server.listen(1)
        yield server.getsockname()[1]


@pytest.fixture
def proxied(backend: SandboxBackend, scene: Scene) -> Iterator[tuple[int, Scene]]:
    require_network_rules(backend)
    with Proxy(["127.0.0.1"]) as proxy:
        yield proxy.port, scene


def _connect(backend: SandboxBackend, scene: Scene, proxy_port: int, host: str, port: int) -> str:
    policy = scene.policy().model_copy(update={"proxy_port": proxy_port})
    result = run_confined(backend, policy, [sys.executable, "-c", CONNECT, host, str(port)])
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_a_direct_connection_to_a_name_fails(
    backend: SandboxBackend, proxied: tuple[int, Scene]
) -> None:
    proxy_port, scene = proxied
    with listening("127.0.0.1") as port:
        assert _connect(backend, scene, proxy_port, "localhost", port) == "PermissionError"


def test_a_direct_connection_to_an_ip_fails(
    backend: SandboxBackend, proxied: tuple[int, Scene]
) -> None:
    proxy_port, scene = proxied
    with listening("127.0.0.2") as port:
        assert _connect(backend, scene, proxy_port, "127.0.0.2", port) == "PermissionError"


def test_a_connection_to_another_local_port_fails(
    backend: SandboxBackend, proxied: tuple[int, Scene]
) -> None:
    proxy_port, scene = proxied
    with listening("127.0.0.1") as port:
        assert _connect(backend, scene, proxy_port, "127.0.0.1", port) == "PermissionError"


def test_the_connection_to_the_proxy_works(
    backend: SandboxBackend, proxied: tuple[int, Scene]
) -> None:
    proxy_port, scene = proxied

    assert _connect(backend, scene, proxy_port, "127.0.0.1", proxy_port) == "connected"


def _fetch(backend: SandboxBackend, scene: Scene, proxy_port: int, url: str) -> str:
    policy = scene.policy().model_copy(update={"proxy_port": proxy_port})
    environment = {
        key: value for key, value in os.environ.items() if key.lower() != "no_proxy"
    } | proxy_environment(proxy_port)
    result = run_confined(backend, policy, [sys.executable, "-c", FETCH, url], env=environment)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_a_request_to_an_allowed_host_succeeds_through_the_proxy_environment(
    backend: SandboxBackend, proxied: tuple[int, Scene]
) -> None:
    proxy_port, scene = proxied
    with upstream() as port:
        assert _fetch(backend, scene, proxy_port, f"http://127.0.0.1:{port}/") == UPSTREAM_BODY


def test_a_request_to_another_host_is_refused_naming_it(
    backend: SandboxBackend, proxied: tuple[int, Scene]
) -> None:
    proxy_port, scene = proxied

    answer = _fetch(backend, scene, proxy_port, "http://example.com/")

    assert answer.startswith("403")
    assert "example.com" in answer
