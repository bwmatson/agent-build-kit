"""A round leaves out a planned unit that has never started when its tier 2 split is held for
its repo, and treats every other unit as it does without the hold (spec: split-start-gate)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW, PLANNED
from tests.parked_split_support import hold, park
from tests.split_start_support import fresh, gate_round, installation, round_ids, store_of, worked

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def stubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    gate_round(monkeypatch)


def test_a_never_started_unit_in_a_held_split_is_not_started_and_nothing_is_made_for_it(
    tmp_path: Path,
) -> None:
    inst = installation(tmp_path, acp=True)
    store = store_of(inst)
    fresh(store, "gated/1", "acp")

    assert round_ids(inst, store) == []

    kept = store.get("gated/1")
    assert (kept.state, kept.branch, kept.pr) == (PLANNED, "", None)


def test_a_ready_unit_in_rest_starts_in_the_round_that_leaves_the_held_one_out(
    tmp_path: Path,
) -> None:
    inst = installation(tmp_path, acp=True)
    store = store_of(inst)
    fresh(store, "gated/1", "acp")
    fresh(store, "free/1", "rest")

    assert round_ids(inst, store) == ["free/1"]


def test_a_unit_in_rest_is_gated_only_when_rest_itself_is_held(tmp_path: Path) -> None:
    inst = installation(tmp_path, acp=False, rest=True)
    store = store_of(inst)
    fresh(store, "plain/1", "rest")
    fresh(store, "acp/1", "acp")

    assert round_ids(inst, store) == ["acp/1"]


def test_a_hold_of_the_configuration_set_false_starts_the_unit_whatever_the_file_holds(
    tmp_path: Path,
) -> None:
    inst = installation(tmp_path, acp=False, claude_code=True)
    hold(inst, "acp")
    store = store_of(inst)
    fresh(store, "free/1", "acp")
    fresh(store, "gated/1", "claude_code")

    assert round_ids(inst, store) == ["free/1"]


def test_a_hold_in_the_state_file_alone_gates_the_unit(tmp_path: Path) -> None:
    inst = installation(tmp_path, acp=None)
    hold(inst, "acp")
    store = store_of(inst)
    fresh(store, "gated/1", "acp")

    assert round_ids(inst, store) == []


def with_a_branch(store: UnitStore) -> None:
    worked(store, "other/1")


def pushed(store: UnitStore) -> None:
    worked(store, "other/1")
    store.record_push("other/1", "abc1234")


def in_review(store: UnitStore) -> None:
    worked(store, "other/1")
    store.set_state("other/1", IN_REVIEW, branch="spec/other/1", pr=3)


def reworking(store: UnitStore) -> None:
    worked(store, "other/1", cause=Cause.REWORK)


def failed(store: UnitStore) -> None:
    worked(store, "other/1")
    store.set_state("other/1", FAILED, note="stopped")


def held_by_person(store: UnitStore) -> None:
    worked(store, "other/1")
    store.set_state("other/1", HELD, note="a person took over")


def parked_at_tier_2(store: UnitStore) -> None:
    park(store, "other/1", ("acp",))


UNGATED = [
    pytest.param(with_a_branch, id="a-branch"),
    pytest.param(pushed, id="a-pushed-commit"),
    pytest.param(in_review, id="in-review"),
    pytest.param(reworking, id="reworking"),
    pytest.param(failed, id="failed"),
    pytest.param(held_by_person, id="held"),
    pytest.param(parked_at_tier_2, id="parked-at-tier-2"),
]


@pytest.mark.parametrize("setup", UNGATED)
def test_a_unit_that_has_work_or_is_not_planned_is_treated_as_without_the_hold(
    tmp_path: Path, setup: Callable[[UnitStore], None]
) -> None:
    def started(name: str, held: bool) -> list[str]:
        inst = installation(tmp_path / name, acp=held)
        store = store_of(inst)
        setup(store)
        fresh(store, "gated/1", "acp")
        return round_ids(inst, store)

    without = started("free", held=False)
    with_hold = started("held", held=True)

    assert "gated/1" in without and "gated/1" not in with_hold
    assert with_hold == [uid for uid in without if uid != "gated/1"]


def test_a_unit_whose_split_its_repo_no_longer_declares_is_not_gated(tmp_path: Path) -> None:
    inst = installation(tmp_path, acp=True)
    store = store_of(inst)
    fresh(store, "gone/1", "gpu")
    fresh(store, "gated/1", "acp")

    assert round_ids(inst, store) == ["gone/1"]


def test_a_unit_depending_on_a_gated_unit_waits_on_it_and_does_not_start(
    tmp_path: Path,
) -> None:
    inst = installation(tmp_path, acp=True)
    store = store_of(inst)
    fresh(store, "gated/1", "acp")
    fresh(store, "child/1", "rest", depends_on=("gated/1",))

    assert round_ids(inst, store) == []
    assert store.get("child/1").branch == ""
