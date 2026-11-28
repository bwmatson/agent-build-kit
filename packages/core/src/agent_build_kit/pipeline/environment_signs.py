"""The environment signs: which failed outputs are the environment's, confirmed by a probe."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import NamedTuple

from agent_build_kit.config import RepoConfig
from agent_build_kit.model import Frozen


class Verdict(StrEnum):
    FAILS = "fails"
    PASSES = "passes"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Probes:
    """The four questions a sign's probe asks; each answers a `Verdict`."""

    forge_read: Callable[[str, str], Verdict]
    feed: Callable[[str, str | None], Verdict]
    credential: Callable[[str], Verdict]
    tool: Callable[[str], Verdict]


class Seen(Frozen):
    sign: str
    subject: str | None
    line: str


class Confirmed(Frozen):
    sign: str
    subject: str | None
    line: str
    note: str


class EnvironmentFailure(RuntimeError):
    """A confirmed environment failure; its text is the note."""

    confirmed: Confirmed


class ParkedSign(NamedTuple):
    sign: str
    subject: str | None


def seen(output: str, step: str, *, tools: Sequence[str] = ()) -> list[Seen]:
    raise NotImplementedError


def distrusted_input(
    sign: str, changed: Sequence[str], repo_config: RepoConfig | None
) -> str | None:
    raise NotImplementedError


def confirm(
    output: str,
    *,
    where: str,
    repo: str,
    branch: str,
    changed: Sequence[str],
    repo_config: RepoConfig | None,
    probes: Probes,
    say: Callable[[str], None],
) -> Confirmed | None:
    raise NotImplementedError


def parked_sign(note: str) -> ParkedSign | None:
    raise NotImplementedError
