"""Admission under a lock: count occupancy, check limits and mark the units admitted."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import Unit

STARTING_TTL = timedelta(seconds=120)


def admit(
    inst: Installation,
    store: UnitStore,
    candidates: Sequence[Unit],
    *,
    worker: str,
    ttl: timedelta = STARTING_TTL,
) -> list[Unit]:
    """The leading `candidates` that fit the free slots, each marked `starting` for `worker`
    until `ttl` from now, all under `runs/locks/admission.lock`."""
    raise NotImplementedError
