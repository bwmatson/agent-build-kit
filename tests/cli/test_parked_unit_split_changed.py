"""A parked unit whose group's `Split:` changed away from its park is released once, as a rework
(spec: a-parked-unit-follows-its-groups-split)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason, UnitStore
from agent_build_kit.pipeline.units import PLANNED, RUNNING, UnitState
from agent_build_kit.pipeline.work_graph import declared_split_names, validate_tasks
from tests.parked_split_support import hold, installation, park, store_of
from tests.split_changed_support import UNIT, Reworks, write_split

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return installation(tmp_path, acp=True, claude_code=False)


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    store = store_of(inst)
    park(store, splits=("acp",), split="acp")
    return store


def test_a_group_that_now_says_another_split_is_delivered_one_rework_and_the_park_ends(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    thread = Reworks(monkeypatch, store)
    write_split(inst, "claude_code")
    capsys.readouterr()

    cli.release_split_changed(inst, store)

    [call] = thread.calls
    assert (call["unit"], call["kind"], call["requeue"]) == (
        UNIT,
        "requeue",
        RequeueReason.FROM_FAILURE,
    )
    assert call["reason"] == "its group's Split changed from acp to claude_code"
    note = call["guidance"].lower()
    assert "acp" in note and "claude_code" in note and "group 1" in note
    assert "task text changed" in note
    assert "read" in note and "again" in note
    after = store.get(UNIT)
    assert after.parked_splits == []
    assert (after.parked_sha, after.parked_snapshot) == ("", "")
    assert after.split == "claude_code"
    [line] = [x for x in capsys.readouterr().out.splitlines() if UNIT in x]
    assert "acp" in line and "claude_code" in line


def test_a_second_pass_over_the_same_store_releases_nothing(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)
    write_split(inst, "claude_code")

    cli.release_split_changed(inst, store)
    cli.release_split_changed(inst, store)

    assert len(thread.calls) == 1
    assert store.get(UNIT).state == RUNNING


def test_units_whose_split_did_not_change_or_moved_to_their_park_stay_parked_unwritten(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)
    park(store, "backstop/1", ("acp",), split="rest")
    park(store, "moved/1", ("acp",), split="rest")
    write_split(inst, "acp")
    write_split(inst, None, change="backstop")
    write_split(inst, "acp", change="moved")
    before = {uid: store.get(uid) for uid in (UNIT, "backstop/1", "moved/1")}

    cli.release_split_changed(inst, store)

    assert thread.calls == []
    assert {uid: store.get(uid) for uid in before} == before


def test_units_the_rule_does_not_apply_to_are_neither_delivered_nor_written(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)
    others = ("flying", "running", "unplanned", "requeued", "gated", "empty")
    for name in others:
        park(store, f"{name}/1", ("acp",), split="acp")
    park(store, "empty/1", (), split="acp")
    store.set_state("running/1", RUNNING, branch="spec/running/1")
    store.set_state("unplanned/1", UnitState.UNPLANNED, branch="spec/unplanned/1")
    store.set_state("requeued/1", PLANNED, branch="spec/requeued/1", cause=Cause.REQUEUED)
    store.set_state("gated/1", PLANNED, branch="spec/gated/1", cause=Cause.GATED)
    for name in ("feature", *others):
        write_split(inst, "claude_code", change=name)
    ids = [f"{name}/1" for name in others]
    before = {uid: store.get(uid) for uid in ids}

    cli.release_split_changed(inst, store, in_flight={"flying/1"})

    assert [call["unit"] for call in thread.calls] == [UNIT], "only the planned, split-held one"
    assert {uid: store.get(uid) for uid in ids} == before


@pytest.mark.parametrize(
    "groups, carried",
    [(("claude_code", "acp"), (1, 2)), (("claude_code",), (1, 2))],
    ids=["two splits", "group missing"],
)
def test_groups_that_do_not_read_as_one_split_leave_the_unit_parked(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    groups: tuple[str, ...],
    carried: tuple[int, ...],
) -> None:
    thread = Reworks(monkeypatch, store)
    store.upsert([store.get(UNIT).model_copy(update={"groups": carried})])
    write_split(inst, *groups)
    _, errors = validate_tasks(
        inst.changes_dir / "feature" / "tasks.md",
        repos=tuple(inst.repos),
        splits=declared_split_names(inst.repos, inst.config),
    )
    assert errors == [], "the file is valid, so the unit's groups are what is wrong"
    before = store.get(UNIT)

    cli.release_split_changed(inst, store)

    assert thread.calls == []
    assert store.get(UNIT) == before


def test_a_tasks_file_that_abk_tags_refuses_leaves_the_unit_parked(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)
    write_split(inst, "claude_code")
    path = inst.changes_dir / "feature" / "tasks.md"
    path.write_text(path.read_text().replace("[e2e-test]", "[nonsense]"))
    before = store.get(UNIT)

    cli.release_split_changed(inst, store)

    assert thread.calls == []
    assert store.get(UNIT) == before


def test_a_busy_branch_leaves_the_unit_as_it_was_and_the_next_pass_delivers(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)
    thread.busy = (UNIT,)
    write_split(inst, "claude_code")
    before = store.get(UNIT)

    cli.release_split_changed(inst, store)

    assert store.get(UNIT) == before
    thread.busy = ()
    cli.release_split_changed(inst, store)
    assert [call["unit"] for call in thread.calls] == [UNIT]
    assert store.get(UNIT).split == "claude_code"


def test_a_unit_with_no_thread_stores_the_guidance_and_is_requeued(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store, thread=False)
    write_split(inst, "claude_code")

    cli.release_split_changed(inst, store)

    after = store.get(UNIT)
    [call] = thread.calls
    assert call["guidance"] and after.guidance == call["guidance"]
    assert (after.state, after.cause) == (PLANNED, Cause.REQUEUED)
    assert "acp" in after.note and "claude_code" in after.note
    assert (after.parked_splits, after.split) == ([], "claude_code")


def test_a_reworked_unit_that_parks_again_on_its_new_held_split_is_not_reworked_again(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)
    write_split(inst, "claude_code")
    cli.release_split_changed(inst, store)
    hold(inst, "claude_code")
    park(store, splits=("claude_code",), split="claude_code")

    cli.release_split_changed(inst, store)

    assert len(thread.calls) == 1
    assert store.get(UNIT).parked_splits == ["claude_code"]
