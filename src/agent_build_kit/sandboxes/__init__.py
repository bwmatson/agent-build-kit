"""The sandbox backends a machine can confine an agent step with."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from agent_build_kit.sandboxes.base import (
    Availability,
    Coverage,
    SandboxBackend,
    SandboxPolicy,
    SandboxUnavailable,
)


def register(backend: SandboxBackend) -> None:
    raise NotImplementedError


def get(name: str) -> SandboxBackend:
    raise NotImplementedError


def names() -> list[str]:
    raise NotImplementedError


def detect(platform: str | None = None) -> SandboxBackend:
    """The first of `landlock`, `seatbelt`, `unavailable` whose platform matches `platform`
    (default `sys.platform`) and whose `availability()` is ok."""
    raise NotImplementedError


@contextmanager
def isolated() -> Iterator[None]:
    """A context manager: inside, the registry holds only the `unavailable` backend; leaving
    puts back what was registered."""
    raise NotImplementedError


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
