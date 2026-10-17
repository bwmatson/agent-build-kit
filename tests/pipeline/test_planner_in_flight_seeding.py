"""A store of hundreds of units is seeded in one write, not one rewrite of the file per unit, so
the time a test spends on it does not grow with the load on the machine."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline import unit_store
from agent_build_kit.pipeline.units import FAILED, MERGED
from tests.cli.replan_driver import Replan, seed_landed_and_planned, tasks_md

OLD = "a-change-whose-units-all-merged-long-ago"
QUEUED = "a-change-whose-units-are-still-planned"


def test_seeding_hundreds_of_units_rewrites_the_store_file_at_most_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1))
    writes: list[Path] = []
    write = unit_store.atomic_write_text

    def counting(path: Path, text: str) -> None:
        writes.append(path)
        write(path, text)

    monkeypatch.setattr(unit_store, "atomic_write_text", counting)

    seed_landed_and_planned(run, old=OLD, queued=QUEUED)

    assert len(writes) <= 1


def test_the_seeded_store_holds_every_unit_in_the_state_the_scenario_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1))

    seed_landed_and_planned(run, old=OLD, queued=QUEUED)

    stored = {u.id: u for u in run.store.all()}
    assert len(stored) == 360 + 140 + 12
    assert all(stored[f"{OLD}/{n}"].state == MERGED for n in range(1, 361))
    assert all(stored[f"misc/{n}"].state == FAILED for n in range(1, 13))
    assert stored[f"{QUEUED}/1"].state not in (MERGED, FAILED)
    assert stored[f"{OLD}/7"].branch == f"spec/{OLD}/7"
    assert stored[f"{OLD}/7"].pr == 7
