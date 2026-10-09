"""The one shared way for a test to wait for a condition."""

from __future__ import annotations

from collections.abc import Callable


def wait_for(condition: Callable[[], bool], *, what: str, timeout: float = 10.0) -> None:
    """Return once `condition()` is true; raise TimeoutError naming `what` after `timeout`
    seconds. The timeout is only an upper bound for a condition that never comes true."""
    raise NotImplementedError
