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
from tests.chat_serving import WAIT


@pytest.fixture(name="api")
def socket_api(inst: Installation) -> Iterator[httpx.Client]:
    """A client of a server running over `inst`.

    A request over a socket waits up to `WAIT`, as a streamed turn does, because httpx's 5-second
    default is shorter than a loaded machine takes to answer; a test whose subject is a timeout
    names its own on the call.
    """
    with start_server(inst) as server, httpx.Client(base_url=server.url, timeout=WAIT) as client:
        yield client
