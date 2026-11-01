"""Whether a unit may start, given who owns the board items it covers (spec: unit-claim)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.units import Unit


class StartDecision(Frozen):
    """The answer for one unit: start it, skip it (someone else owns it) or wait (the board is
    not ready). `items` holds the ids of the board items the reason is about."""

    outcome: Literal["start", "skip", "wait"]
    reason: str = ""
    items: tuple[str, ...] = ()


def start_decision(unit: Unit, *, changes_dir: Path) -> StartDecision:
    """The decision for `unit` against the tracker of its repo, whose tracker files are under
    `changes_dir`; a repo with no tracker section starts it and makes no call."""
    raise NotImplementedError


def start_view(graph: Sequence[Unit], decide: Callable[[Unit], StartDecision]) -> list[Unit]:
    """`graph` with each planned unit `decide` does not start shown as held, so it takes no
    slot and the next ready unit is considered."""
    raise NotImplementedError
