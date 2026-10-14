"""The `api` fixture over a real socket, for the tests whose subject only a socket shows: a
page that closes mid-stream, a request that times out while the store is locked.

The in-process client of `conftest.py` answers a request with a function call and cannot
be closed half way or time out, so a module of such tests imports this fixture, which
overrides it (`from tests.serve.socket_api import socket_api  # noqa: F401`). It is the only place
besides the modules on `tests/serve_sockets.py`'s allowlist that serves over a socket.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.serve.server import start_server


@pytest.fixture(name="api")
def socket_api(inst: Installation) -> Iterator[httpx.Client]:
    """A client of a server running over `inst`."""
    with start_server(inst) as server, httpx.Client(base_url=server.url) as client:
        yield client
