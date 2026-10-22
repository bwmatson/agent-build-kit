"""The sandbox backends a machine can confine an agent step with.

The same shape as `forges`: filled in-process, no plugin discovery, and an unknown name says
which names it knows.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager

from agent_build_kit.sandboxes.base import (
    Availability,
    Coverage,
    SandboxBackend,
    SandboxPolicy,
    SandboxUnavailable,
)

_REGISTRY: dict[str, SandboxBackend] = {}

# The order `detect` asks in; `unavailable` is last and always answers.
_ORDER = ("landlock", "seatbelt", "unavailable")


def register(backend: SandboxBackend) -> None:
    _load_builtin()
    _REGISTRY[backend.name] = backend


def get(name: str) -> SandboxBackend:
    _load_builtin()
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown sandbox backend {name!r} (known: {', '.join(names())})") from None


def names() -> list[str]:
    _load_builtin()
    return sorted(_REGISTRY)


def detect(platform: str | None = None) -> SandboxBackend:
    """The first of `landlock`, `seatbelt`, `unavailable` whose platform matches `platform`
    (default `sys.platform`) and whose `availability()` is ok."""
    _load_builtin()
    here = sys.platform if platform is None else platform
    for name in _ORDER:
        backend = _REGISTRY.get(name)
        if backend and here.startswith(backend.platform) and backend.availability().ok:
            return backend
    return _REGISTRY["unavailable"]


@contextmanager
def isolated() -> Iterator[None]:
    """Inside, the registry holds only the `unavailable` backend; leaving puts back what was
    registered."""
    saved = dict(_REGISTRY)
    _REGISTRY.clear()
    try:
        _load_builtin()
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(saved)


def _load_builtin() -> None:
    if _REGISTRY:
        return
    from agent_build_kit.sandboxes import landlock, unavailable

    for backend in (landlock.BACKEND, unavailable.BACKEND):
        _REGISTRY[backend.name] = backend


__all__ = [
    "Availability",
    "Coverage",
    "SandboxBackend",
    "SandboxPolicy",
    "SandboxUnavailable",
    "detect",
    "get",
    "isolated",
    "names",
    "register",
]
