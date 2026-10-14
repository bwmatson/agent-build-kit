"""The one shared way for a test to wait for a condition."""

from __future__ import annotations

import threading
from collections.abc import Callable

POLL = 0.01


def wait_for(
    condition: Callable[[], object],
    *,
    what: str,
    timeout: float = 10.0,
    failure: Callable[[], str | None] | None = None,
) -> None:
    """Return once `condition()` is true; raise TimeoutError naming `what` after `timeout`
    seconds. The timeout is only an upper bound for a condition that never comes true.
    `failure` says why it never will, when it can (an agent process's stderr once it has
    exited): while it returns text, the wait ends at once with a RuntimeError carrying it."""
    never = threading.Event()
    waited = 0.0
    while not condition():
        if failure is not None and (said := failure()):
            raise RuntimeError(f"gave up waiting for {what}: {said}")
        if waited >= timeout:
            raise TimeoutError(f"timed out after {timeout:g} seconds waiting for {what}")
        never.wait(POLL)
        waited += POLL
