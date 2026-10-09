"""The one shared way for a test to wait for a condition."""

from __future__ import annotations

import threading
from collections.abc import Callable

POLL = 0.01


def wait_for(condition: Callable[[], bool], *, what: str, timeout: float = 10.0) -> None:
    """Return once `condition()` is true; raise TimeoutError naming `what` after `timeout`
    seconds. The timeout is only an upper bound for a condition that never comes true."""
    never = threading.Event()
    waited = 0.0
    while not condition():
        if waited >= timeout:
            raise TimeoutError(f"timed out after {timeout:g} seconds waiting for {what}")
        never.wait(POLL)
        waited += POLL
