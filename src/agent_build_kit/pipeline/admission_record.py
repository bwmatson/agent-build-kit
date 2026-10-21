"""The admission records: why a unit was admitted or held at a slot, written beside the
decision log (spec: capacity-checks, admission leaves a record that explains it)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen

# The admission records, in the state directory.
ADMISSIONS_NAME = "admissions.jsonl"


class Counted(Frozen):
    """A unit counted in a slot, and why it counts: its state, and the pull request, branch or
    pushed commit that makes it so."""

    id: str
    state: str
    why: str


class UsageFacts(Frozen):
    """The unit's own account's usage decision, as made."""

    may_start: bool
    reason: str
    source: str = ""
    age_seconds: float | None = None
    threshold: float | None = None
    ramp: float | None = None
    estimate: bool = False
    estimate_starts: int = 0


class AdmissionRecord(Frozen):
    """One admission (`admitted`) or one wait for a slot (`slot`). The slot is the account's
    label (`default` for the default account), or the project's tag when units are counted per
    project."""

    at: datetime
    kind: Literal["admitted", "slot"]
    unit: str
    tick: str
    slot: str
    limit: int
    counted: tuple[Counted, ...]
    usage: UsageFacts
    fingerprint: str


class SlotCount(Frozen):
    """What one slot counted in a tick: the ids, the limit and the room left."""

    slot: str
    limit: int
    ids: tuple[str, ...]
    room: int


class TickCounts(Frozen):
    """The per-slot counts of a tick that started or refused a unit."""

    at: datetime
    tick: str
    fingerprint: str
    slots: tuple[SlotCount, ...]


def read_admissions(path: Path) -> list[AdmissionRecord]:
    """The admission and slot-wait records in the file at `path`, oldest first."""
    raise NotImplementedError


def read_counts(path: Path) -> list[TickCounts]:
    """The per-tick counts in the file at `path`, oldest first."""
    raise NotImplementedError


def config_fingerprint(inst: Installation) -> str:
    """A hash of the installation's merged configuration and the modification times of
    `abk.yaml` and `abk.local.yaml`."""
    raise NotImplementedError
