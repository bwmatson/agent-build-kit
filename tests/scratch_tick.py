"""What live tests share to run `abk tick` in a scratch installation and read a unit's branch."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from agent_build_kit.model import Frozen

# The program a tick runs, replaceable by a test that stands in for it.
ABK: Path = Path("abk")


class Scratch(Protocol):
    """What the helpers need of a live test's scratch installation."""

    @property
    def planning(self) -> Path: ...

    @property
    def remote(self) -> Path: ...

    @property
    def state(self) -> Path: ...

    @property
    def env(self) -> dict[str, str]: ...


class TickResult(Frozen):
    """One `abk tick`: its return code, its output lines with the second each arrived at."""

    returncode: int
    lines: tuple[tuple[float, str], ...]
    started: float
    ended: float

    @property
    def output(self) -> str:
        raise NotImplementedError


def run_tick(scratch: Scratch, *, timeout: float = 3600) -> TickResult:
    raise NotImplementedError


def ticks_of(scratch: Scratch) -> tuple[TickResult, ...]:
    """The last three ticks run in `scratch`, oldest first."""
    raise NotImplementedError


def scratch_env_summary(env: Mapping[str, str]) -> list[str]:
    raise NotImplementedError


def commits_on_unit_branch(
    scratch: Scratch, branch: str, tick: TickResult | None = None
) -> list[str]:
    raise NotImplementedError
