"""A verdict record gains an outcome derived from the unit's history (spec: review-outcomes).

The forge is the stand-in and answers a merge commit the temporary checkout does not hold, so
the revert search cannot run and only the history decides here; the revert rule has its own
tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.forges.base import RepoId
from agent_build_kit.pipeline.review_outcome import with_outcome
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import UnitState
from tests.factories import commit, init_repo, stored_unit
from tests.forges.stand_in import StandInForge

UID = "add-marker/1"
REPO = RepoId(forge="stand_in", account="example", name="app")


def entry(state: str, cause: str = "") -> dict:
    return {
        "state": state,
        "at": "2026-10-01T10:00:00+00:00",
        **({"cause": cause} if cause else {}),
    }


def unit_with(state: UnitState, *causes: str) -> StoredUnit:
    history = (entry("running"),) + tuple(entry("running", cause) for cause in causes)
    return stored_unit(UID, state=state, pr=7, history=history)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "app")
    commit(repo, "base.txt")
    return repo


def derive(unit: StoredUnit, checkout: Path, records: dict | None = None) -> dict:
    forge = StandInForge()
    forge.merged[7] = "a" * 40
    given = {UID: {"brief": True}} if records is None else records
    return with_outcome(given, unit, forge=forge, repo=REPO, checkout=checkout, trunk="main")


def test_a_unit_merged_by_a_person_with_no_rework_is_clean(checkout: Path) -> None:
    record = derive(unit_with(UnitState.MERGED, "merged"), checkout)[UID]

    assert record["outcome"] == "clean"
    assert record["reworks"] == 0
    assert record["revert_checked"] is False
    assert record["brief"] is True


def test_a_unit_merged_after_rework_is_reworked_with_the_count(checkout: Path) -> None:
    unit = unit_with(UnitState.MERGED, "rework", "base_changed", "rework", "merged")

    record = derive(unit, checkout)[UID]

    assert record["outcome"] == "reworked"
    assert record["reworks"] == 2


def test_a_unit_not_yet_merged_is_open(checkout: Path) -> None:
    assert derive(unit_with(UnitState.IN_REVIEW, "rework"), checkout)[UID]["outcome"] == "open"


def test_a_unit_closed_unmerged_is_closed(checkout: Path) -> None:
    assert derive(unit_with(UnitState.CLOSED, "closed"), checkout)[UID]["outcome"] == "closed"


def test_deriving_twice_gives_equal_results(checkout: Path) -> None:
    unit = unit_with(UnitState.MERGED, "rework", "merged")
    records = {UID: {"brief": True}}

    first = derive(unit, checkout, records)
    second = derive(unit, checkout, records)

    assert first == second
    assert records == {UID: {"brief": True}}


def test_a_unit_with_no_verdict_record_is_left_alone(checkout: Path) -> None:
    records = {"other/1": {"brief": True}}

    assert derive(unit_with(UnitState.MERGED, "merged"), checkout, records) == records
