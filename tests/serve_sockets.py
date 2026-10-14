"""The guard against a socket in a tier 1 test under `tests/serve`.

A module that is not marked `integration` (a module-level `pytestmark` naming
`pytest.mark.integration`) must not, found by parsing it (strings and comments never count):
  - import or name `uvicorn`, `socket`, `http.client` or `ThreadingHTTPServer`;
  - call `start_server`, which serves the application over a socket;
  - build an `httpx.Client` whose `base_url` is anything but `http://testserver`.
`check_serve_tests` returns one message per problem, each naming `path:line`; files are
paths under `root`, all of its `.py` files unless `only` lists them.
"""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path

SERVE_TESTS = Path(__file__).parent / "serve"

# The in-process client's base URL: the one an ASGI transport answers.
IN_PROCESS_URL = "http://testserver"


def check_serve_tests(root: Path, only: Collection[str] | None = None) -> list[str]:
    raise NotImplementedError
