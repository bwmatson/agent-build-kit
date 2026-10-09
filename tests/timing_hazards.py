"""The guard against timing hazards in the test tree.

A hazard is, found by parsing a file (strings and comments never count):
  - "sleep": a call to `time.sleep` or `asyncio.sleep`;
  - "thread": a function that constructs a `threading.Thread` and neither calls
    `.join(` nor `.set(` in the same function;
  - "port": a call that passes a non-zero integer literal as `port=`, or whose first
    argument is a `(host, <non-zero integer literal>)` tuple.
`check_tests` returns one message per problem: a hazard in a file that is neither shared
nor allowlisted names `path:line`; an allowlisted file with no hazard (or none at all) is
reported as a stale allowlist entry naming the file.
"""

from __future__ import annotations

from pathlib import Path

TESTS_ROOT = Path(__file__).parent

# Files of shared helpers that may hold a hazard, as paths under the tests root.
SHARED_HELPERS: frozenset[str] = frozenset()

# Files with hazards today, as paths under the tests root. It may only shrink.
ALLOWLIST: frozenset[str] = frozenset()


def check_tests(root: Path, *, allowlist: frozenset[str], shared: frozenset[str]) -> list[str]:
    raise NotImplementedError
