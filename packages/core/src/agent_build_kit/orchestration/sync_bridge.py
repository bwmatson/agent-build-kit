"""The transitional bridge: synchronous callers reach the async `UnitsStore` through `run_store`."""

from __future__ import annotations

from collections.abc import Coroutine
from typing import Any


def run_store[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run `coro` to completion from synchronous code and return its result; raise when called
    inside a running event loop."""
    raise NotImplementedError
