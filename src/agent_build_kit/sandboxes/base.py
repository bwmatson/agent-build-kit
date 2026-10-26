"""What a sandbox backend has to answer, and the values it answers with.

A `Protocol`, not a base class, as `forges.base.Forge` is: a backend owns its own code and a
test stand-in is a plain class (`tests/sandboxes/stand_in.py`).
"""

from __future__ import annotations

import sys
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


def step_confined(required: Coverage, coverage: Coverage) -> bool:
    """Whether a step of a repo that `required` this much runs confined on a runtime with
    `coverage`: `none` lets it run plain, and less coverage than required runs it plain too."""
    return required is not Coverage.NONE and coverage.reaches(required)


LINUX_SYSTEM_FOLDERS = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc", "/proc", "/sys")
MACOS_SYSTEM_FOLDERS = ("/usr", "/bin", "/sbin", "/System", "/Library", "/private/etc", "/dev")


def system_folders() -> tuple[str, ...]:
    """The system folders every confined step reads on this platform, so it can exec anything;
    only those that exist."""
    named = MACOS_SYSTEM_FOLDERS if sys.platform == "darwin" else LINUX_SYSTEM_FOLDERS
    return tuple(folder for folder in named if Path(folder).exists())


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
    # Paths under `read` that a step may read and never execute.
    no_execute: tuple[Path, ...] = ()


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
