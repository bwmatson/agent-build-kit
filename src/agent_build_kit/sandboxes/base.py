"""What a sandbox backend has to answer, and the values it answers with.

A `Protocol`, not a base class, as `forges.base.Forge` is: a backend owns its own code and a
test stand-in is a plain class (`tests/sandboxes/stand_in.py`).
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from agent_build_kit.model import Frozen


class Coverage(StrEnum):
    """How much of a process a backend confines."""

    PROCESS = "process"
    FILES = "files"
    NONE = "none"


class Availability(Frozen):
    """Whether a backend works on this machine, and what it reaches when it does."""

    ok: bool
    coverage: Coverage
    cause: str = ""
    fix: str = ""


class SandboxPolicy(Frozen):
    """What a confined process may touch: the lists, resolved to absolute paths."""

    write: tuple[Path, ...]
    read: tuple[Path, ...]
    hosts: tuple[str, ...]
    # The least coverage a step may run with; `none` lets it run unconfined.
    required: Coverage


class SandboxUnavailable(Exception):
    """No backend can be applied here; the message names the cause and the fix."""


class SandboxBackend(Protocol):
    name: str
    # The `sys.platform` prefix this backend runs on; empty for any.
    platform: str

    def availability(self) -> Availability: ...

    def command(self, policy: SandboxPolicy, argv: Sequence[str]) -> list[str]: ...
