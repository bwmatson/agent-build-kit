"""`abk requeue` of a unit parked on a split (spec: a-unit-parked-on-a-split-can-be-requeued):
`--rework` and `--restart` deliver it and clear its park, a plain requeue is judged by the
splits it is parked on, and a unit that is not parked, has a pull request or is being built
is refused with nothing changed."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.e2e_holds import remove_hold
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, PLANNED, RUNNING, UnitState
from tests.factories import stored_unit
from tests.parked_split_support import hold, installation, park, store_of
from tests.split_changed_support import UNIT, Reworks, write_split

NOTE = "retag the test; it uses a scripted agent"
REFUSED_BEFORE = "only a failed or held unit can be requeued"


class Said:
    """What `requeue` says, in the order it says it."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, text: str, error: bool = False) -> None:
        self.lines.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return installation(tmp_path, acp=None, claude_code=None, gpu=None)


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    """`feature/1` parked on `acp`, which is held, with a branch and no pull request."""
    store = store_of(inst)
    park(store, splits=("acp",), split="acp")
    hold(inst, "acp")
    return store


def ask(inst: Installation, mode: str, *, note: str = "") -> tuple[int, Said]:
    said = Said()
    return cli.requeue(inst, UNIT, mode, say=said, note=note), said


def parked(unit: StoredUnit) -> bool:
    return bool(unit.parked_splits or unit.parked_sha or unit.parked_snapshot)


def test_a_rework_with_a_note_is_delivered_once_and_the_park_is_cleared(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)

    code, said = ask(inst, "rework", note=NOTE)

    assert code == 0, said.text
    [call] = thread.calls
    assert call["requeue"] is RequeueReason.FROM_FAILURE
    assert call["guidance"] == NOTE
    after = store.get(UNIT)
    assert not parked(after)
    assert after.cause is not Cause.SPLIT_HELD
    entry = after.history[-1]["note"]
    assert "acp" in entry and NOTE in entry
    assert entry.index("acp") < entry.index(NOTE)


def test_a_second_requeue_does_not_find_the_unit_parked(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store, thread=False)
    assert ask(inst, "rework", note=NOTE)[0] == 0
    after = store.get(UNIT)
    assert (after.state, after.cause) == (PLANNED, Cause.REQUEUED) and not parked(after)

    code, said = ask(inst, "rework", note=NOTE)

    assert code == 1
    assert REFUSED_BEFORE in said.text
    assert len(thread.calls) == 1, "the second was not delivered"


def test_a_note_file_is_the_note(
    inst: Installation, store: UnitStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)
    (inst.root / "abk.yaml").write_text(dump(inst.config))
    monkeypatch.chdir(inst.root)
    path = tmp_path / "note.txt"
    path.write_text(NOTE)

    assert main(["requeue", UNIT, "--rework", "--note-file", str(path)]) == 0

    [call] = thread.calls
    assert call["guidance"] == NOTE and call["requeue"] is RequeueReason.FROM_FAILURE
    assert not parked(store.get(UNIT))


def test_a_rework_with_no_note_and_no_saved_failure_gets_an_automatic_guidance_naming_the_split(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)
    assert store.get(UNIT).feedback == ""

    code, said = ask(inst, "rework")

    assert code == 0, said.text
    [call] = thread.calls
    assert "acp" in call["guidance"]
    assert not parked(store.get(UNIT))


def test_with_no_thread_a_rework_stores_the_guidance_and_plans_the_unit_requeued(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    Reworks(monkeypatch, store, thread=False)

    assert ask(inst, "rework")[0] == 0

    after = store.get(UNIT)
    assert (after.state, after.cause) == (PLANNED, Cause.REQUEUED)
    assert "acp" in after.guidance
    assert not parked(after)


def test_a_restart_clears_the_feedback_keeps_the_note_and_clears_the_park(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store, thread=False)
    store.set_feedback(UNIT, "an old failure")

    code, said = ask(inst, "restart", note=NOTE)

    assert code == 0, said.text
    [call] = thread.calls
    assert call["requeue"] is RequeueReason.RESTART
    after = store.get(UNIT)
    assert after.feedback == "" and after.guidance == NOTE
    assert (after.state, after.cause) == (PLANNED, Cause.REQUEUED)
    assert not parked(after)


def test_a_plain_requeue_while_the_split_is_held_changes_nothing_and_says_why(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)
    before = store.get(UNIT)

    code, said = ask(inst, "resume")

    assert code == 1
    assert "is parked on e2e-test split acp (held: the usage window is spent" in said.text
    assert "--rework" in said.text and "release" in said.text
    assert thread.calls == [] and store.get(UNIT) == before


def test_a_plain_requeue_names_every_split_it_is_parked_on_when_one_of_two_is_held(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)
    store.set_parked(UNIT, ("acp", "claude_code"), "abc1234", "snapshot")

    code, said = ask(inst, "resume")

    assert code == 1
    assert "acp" in said.text and "claude_code" in said.text
    assert thread.calls == []


@pytest.mark.parametrize("has_thread", [True, False])
def test_a_plain_requeue_once_the_split_is_released_is_delivered_as_the_release_does(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch, has_thread: bool
) -> None:
    thread = Reworks(monkeypatch, store, thread=has_thread)
    assert remove_hold(inst.state_dir, "acp")

    code, said = ask(inst, "resume")

    assert code == 0, said.text
    [call] = thread.calls
    assert call["requeue"] is RequeueReason.RESUME and call["reason"] == "resume"
    if not has_thread:
        after = store.get(UNIT)
        assert (after.state, after.cause) == (PLANNED, Cause.REQUEUED)


def test_a_plain_requeue_is_delivered_when_only_rest_is_held(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)
    assert remove_hold(inst.state_dir, "acp")
    hold(inst, "rest")

    assert ask(inst, "resume")[0] == 0

    assert [call["requeue"] for call in thread.calls] == [RequeueReason.RESUME]


def test_a_plain_requeue_with_a_note_is_refused_for_the_note(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)
    assert remove_hold(inst.state_dir, "acp")

    code, said = ask(inst, "resume", note=NOTE)

    assert code == 1
    assert "a note is read by the agent" in said.text
    assert thread.calls == []


def test_a_plain_requeue_of_a_unit_whose_group_moved_to_another_split_says_the_pass_reworks_it(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)
    assert remove_hold(inst.state_dir, "acp")
    write_split(inst, "claude_code")
    before = store.get(UNIT)

    code, said = ask(inst, "resume")

    assert code == 1
    assert "rework" in said.text
    assert thread.calls == [] and store.get(UNIT) == before


def test_what_is_not_a_parked_unit_is_refused_as_before_and_a_parked_one_is_not(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)
    # A unit in each state that is refused; only the dropped one keeps the park it was left with.
    states = {
        "running": RUNNING,
        "in-review": IN_REVIEW,
        "merged": MERGED,
        "planned": PLANNED,
        "unplanned": UnitState.UNPLANNED,
    }
    for name, state in states.items():
        uid = f"{name}/1"
        park(store, uid, ("acp",), split="acp")
        dropped = state is UnitState.UNPLANNED
        store.set_state(uid, state, cause=Cause.SPLIT_HELD if dropped else Cause.REQUEUED)
        if not dropped:
            store.set_parked(uid)
    before = {uid: store.get(uid) for uid in (f"{name}/1" for name in states)}

    for uid, unit in before.items():
        said = Said()
        code = cli.requeue(inst, uid, "rework", say=said, note=NOTE)
        assert code == 1, uid
        assert REFUSED_BEFORE in said.text, uid
        assert store.get(uid) == unit, uid
    assert thread.calls == []

    assert ask(inst, "rework", note=NOTE)[0] == 0, "the parked unit beside them is accepted"


def test_a_parked_unit_with_a_pull_request_is_refused_naming_it(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)
    store.set_state(UNIT, PLANNED, pr=42, cause=Cause.SPLIT_HELD)
    before = store.get(UNIT)

    code, said = ask(inst, "rework", note=NOTE)

    assert code == 1
    assert "42" in said.text and "pull request" in said.text.lower()
    assert thread.calls == [] and store.get(UNIT) == before


def test_a_unit_whose_branch_a_step_holds_keeps_its_park_and_is_accepted_once_it_is_free(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Reworks(monkeypatch, store)
    thread.busy = (UNIT,)
    before = store.get(UNIT)

    code, said = ask(inst, "rework", note=NOTE)

    assert code == 1
    assert "is being built" in said.text
    assert store.get(UNIT) == before and parked(before)

    thread.busy = ()
    assert ask(inst, "rework", note=NOTE)[0] == 0
    assert not parked(store.get(UNIT))


def test_a_parked_unit_whose_prerequisite_is_open_is_gated_and_its_history_names_the_splits(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.upsert([stored_unit("dep/1", change="dep", repo="platform")])
    store.set_state("dep/1", IN_REVIEW, pr=3)
    store.set_dependencies(UNIT, ("dep/1",))
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: True)

    code, said = ask(inst, "rework", note=NOTE)

    assert code == 0, said.text
    after = store.get(UNIT)
    assert after.cause is Cause.GATED
    assert not parked(after)
    entry = after.history[-1]["note"]
    assert "acp" in entry and NOTE in entry
