"""Outlines: the far-out work a planning repo keeps as `<outlines>/<name>/proposal.md`, how many
units ahead of being buildable each one is, and which detailed changes touch the same paths
(spec: outlines-are-detailed-one-unit-ahead). Reads only; makes no model call."""

from __future__ import annotations

from collections.abc import Sequence

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit


class WaitsOn(Frozen):
    """One `Waits on: <change or outline> group <n>` line."""

    target: str
    group: int


class Outline(Frozen):
    """One outline as written: the lines a tool reads, and the lines that did not parse."""

    name: str
    initiative: str = ""
    its_part: str = ""
    groups: tuple[int, ...] = ()
    waits_on: tuple[WaitsOn, ...] = ()
    touches: tuple[str, ...] = ()
    reworks: tuple[str, ...] = ()
    # Lines that did not parse (a `Waits on:` with no group number), ignored for the distance.
    unparsed: tuple[str, ...] = ()


class Reading(Frozen):
    """An outline with its distance: None on a cycle, which also names the cycle."""

    outline: Outline
    distance: int | None
    ready: bool
    cycle: tuple[str, ...] = ()
    # Prerequisite names that are neither a change nor an outline.
    not_found: tuple[str, ...] = ()


class Overlap(Frozen):
    """A detailed change and an outline whose paths overlap."""

    change: str
    outline: str
    reworks: int
    # More than two `Reworks:` lines: the outline is detailed sooner.
    promote_earlier: bool


def read_outlines(inst: Installation) -> list[Outline]:
    """Every folder under `planning.outlines` that holds a `proposal.md`, in name order."""
    raise NotImplementedError


def readings(inst: Installation, units: Sequence[StoredUnit]) -> list[Reading]:
    """Each outline's distance over `units`, nearest first, then by name."""
    raise NotImplementedError


def ready_outlines(inst: Installation, units: Sequence[StoredUnit]) -> list[Reading]:
    """The readings whose distance is at most `planning.outline_lead_units`."""
    raise NotImplementedError


def overlaps(inst: Installation) -> list[Overlap]:
    """For each detailed change, each outline whose `Touches:` overlaps a path its tasks name."""
    raise NotImplementedError
