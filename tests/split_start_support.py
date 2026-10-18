"""A planned unit in an e2e-test split, and a round that decides whether it starts (spec:
split-start-gate): the installation that declares the splits, the stand-ins a round reaches, and
the fresh unit the gate is about."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.factories import stored_unit
from tests.parked_split_support import installation, store_of, stub_round

__all__ = ["fresh", "gate_round", "installation", "round_ids", "store_of", "worked"]


def gate_round(monkeypatch: pytest.MonkeyPatch) -> None:
    """What a round reaches that is not under test."""
    stub_round(monkeypatch)
    monkeypatch.setattr(cli, "verify_ready", lambda inst, units, **kwargs: lambda change: True)
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: True)


def fresh(store: UnitStore, uid: str, split: str = "rest", **overrides: Any) -> None:
    """`uid` planned and never started, in `split`."""
    store.upsert([stored_unit(uid, change=uid.partition("/")[0], split=split, **overrides)])


def worked(store: UnitStore, uid: str, split: str = "acp", **state: Any) -> None:
    """`uid` planned with a branch, as a run that stopped leaves it."""
    fresh(store, uid, split)
    store.set_state(uid, PLANNED, branch=f"spec/{uid}", **state)


def round_ids(inst: Installation, store: UnitStore) -> list[str]:
    """The ids one round hands out to start."""
    ready = cli.run_round(inst, store, building=(), only=frozenset(), submit=True)
    return [unit.id for unit in ready]


def scratch(tmp_path: Path, name: str) -> Path:
    return tmp_path / name
