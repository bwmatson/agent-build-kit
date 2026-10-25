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
    step_confined,
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


def _detect(
    platform: str | None, *, keep_failed: bool = False
) -> tuple[SandboxBackend, Availability]:
    _load_builtin()
    here = sys.platform if platform is None else platform
    failed: tuple[SandboxBackend, Availability] | None = None
    for name in _ORDER:
        backend = _REGISTRY.get(name)
        if backend and here.startswith(backend.platform):
            found = backend.availability()
            if found.ok:
                return backend, found
            # `unavailable` matches every platform and always fails: it is the answer for "no
            # backend", never a backend that was tried and broke.
            if failed is None and name != "unavailable":
                failed = (backend, found)
    if keep_failed and failed is not None:
        return failed
    fallback = _REGISTRY["unavailable"]
    return fallback, fallback.availability()


def detect(platform: str | None = None) -> SandboxBackend:
    """The first of `landlock`, `seatbelt`, `unavailable` whose platform matches `platform`
    (default `sys.platform`) and whose `availability()` is ok."""
    return _detect(platform)[0]


def probe(name: str = "auto") -> tuple[SandboxBackend, Availability]:
    """The backend `name` picks (`auto` detects one) and the result of running its probe. For
    `auto`, a backend that matches the platform but fails its probe is returned with that failure,
    and `unavailable` only where no backend matches."""
    if name == "auto":
        return _detect(None, keep_failed=True)
    backend = get(name)
    return backend, backend.availability()


@contextmanager
def isolated() -> Iterator[None]:
    """Inside, the registry holds only the built-in backends (`landlock`, `seatbelt`,
    `unavailable`); leaving puts back what was registered."""
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
    from agent_build_kit.sandboxes import landlock, seatbelt, unavailable

    for backend in (landlock.BACKEND, seatbelt.BACKEND, unavailable.BACKEND):
        _REGISTRY[backend.name] = backend


__all__ = [
    "Availability",
    "Coverage",
    "step_confined",
    "SandboxBackend",
    "SandboxPolicy",
    "SandboxUnavailable",
    "detect",
    "get",
    "isolated",
    "names",
    "probe",
    "register",
]
