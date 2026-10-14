"""Run a fake HTTP server on a thread that is shut down and joined when the block ends."""

from __future__ import annotations

import http.server
import threading
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def serving(server: http.server.HTTPServer) -> Iterator[http.server.HTTPServer]:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
