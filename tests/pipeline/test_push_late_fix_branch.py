"""A late fix's branch (`<branch>-fix<k>`) is found by the branch the unit records, not by the
name's spelling, so each push is recorded on the unit and leased against the one before it
(spec: merged-waits-for-ci). The late failure itself forgets the first branch's head."""

from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.forges import PullRequest
from agent_build_kit.forges.base import Check, CheckStatus
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import Pull, UnitStore, unit_id_of_branch
from agent_build_kit.pipeline.units import SETTLING, UnitState
from agent_build_kit.pipeline.wiring import build_push
from tests.factories import stored_unit

FIX = "spec/add-marker/1-fix1"


def late_failed(tmp_path: Path) -> UnitStore:
    """A settling unit whose first branch was pushed and approved, sent to its late fix."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("add-marker/1")])
    store.set_state("add-marker/1", SETTLING, pr=4, branch="spec/add-marker/1")
    store.record_push("add-marker/1", "first-head")
    store.record_approval("add-marker/1", "first-head")
    store.set_pulls(
        "add-marker/1",
        (Pull(number=4, branch="spec/add-marker/1", merged_at=datetime(2026, 10, 27, tzinfo=UTC)),),
    )
    red = PullRequest(
        number=4,
        head="spec/add-marker/1",
        base="main",
        state="merged",
        checks=(Check(name="test", status=CheckStatus.FAILED),),
    )
    events.on_late_check(
        4, repo="app", pull=red, store=store, base_passes=lambda unit, log: False, log=print
    )
    return store


def test_the_late_failure_forgets_what_described_the_first_branch_head(tmp_path: Path) -> None:
    unit = late_failed(tmp_path).get("add-marker/1")

    assert unit.branch == FIX
    assert unit.state == UnitState.PLANNED
    assert (unit.pr, unit.pushed, unit.pushed_at, unit.approved) == (None, None, None, "")


def test_each_push_of_the_late_fix_is_recorded_on_the_unit_and_leased_on_the_one_before(
    tmp_path: Path,
) -> None:
    store = late_failed(tmp_path)
    leases: list[str | None] = []
    heads = iter(["fix-head-1", "fix-head-2"])

    push = build_push(
        store,
        push=lambda repo, branch, last_pushed: leases.append(last_pushed) or next(heads),
        remote_head_of=lambda repo, branch: None,
    )
    push(FIX, cwd=tmp_path)
    push(FIX, cwd=tmp_path)

    assert leases == [None, "fix-head-1"]
    assert store.get("add-marker/1").pushed == "fix-head-2"


def test_a_branch_is_matched_to_the_unit_that_records_it_before_its_name_is_read() -> None:
    units = [stored_unit("add-marker/1", branch=FIX)]

    assert unit_id_of_branch(units, FIX, "spec/") == "add-marker/1"
    assert unit_id_of_branch(units, "spec/other/2", "spec/") == "other/2"
