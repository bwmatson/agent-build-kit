"""What a sandbox backend has to answer, and the values it answers with.

A `Protocol`, not a base class, as `forges.base.Forge` is: a backend owns its own code and a
test stand-in is a plain class (`tests/sandboxes/stand_in.py`).
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from agent_build_kit.model import Frozen

if TYPE_CHECKING:  # profiles import config, which imports this package
    from agent_build_kit.profiles.base import SandboxPaths


class Coverage(StrEnum):
    """How much of a process a backend confines."""

    PROCESS = "process"
    FILES = "files"
    NONE = "none"

    def reaches(self, needed: Coverage) -> bool:
        """Whether this coverage is at least `needed`."""
        order = (Coverage.NONE, Coverage.FILES, Coverage.PROCESS)
        return order.index(self) >= order.index(needed)


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
    # The local port of the allowlisting proxy: the only one a confined process may connect to.
    proxy_port: int | None = None
    # The local service ports an e2e-test step may connect to, beside the proxy's.
    ports: tuple[int, ...] = ()


class SandboxUnavailable(Exception):
    """No backend can be applied here; the message names the cause and the fix."""


@runtime_checkable
class SandboxPathsRuntime(Protocol):
    """The optional member a runtime adds to grant paths and hosts to its own steps."""

    def sandbox_paths(self, account: Any = None) -> dict[str, list[str]]: ...


@runtime_checkable
class SandboxPathsProfile(Protocol):
    """The optional member a toolchain profile adds to grant what its tools write."""

    def sandbox_paths(self, worktree: Path) -> SandboxPaths | dict[str, list[str]]: ...


class SandboxBackend(Protocol):
    name: str
    # The `sys.platform` prefix this backend runs on; empty for any.
    platform: str

    def availability(self) -> Availability: ...

    def command(self, policy: SandboxPolicy, argv: Sequence[str]) -> list[str]: ...
