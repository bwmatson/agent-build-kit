"""A stored unit that joined several `[e2e-test]` groups is split by the next plan when it has not
started and kept whole when it has (spec: unit-joining). Nothing rewrites a stored unit by
itself: the plan that would keep the groups together is refused, and the store stays as it was."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, UnitState
from tests.cli.replan_driver import Replan, answer, planned, tagged_md
from tests.factories import stored_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

E2E = "e2e-test"


def e2e(uid: str, numbers: tuple[int, ...], **fields) -> dict:
    return dict(planned(uid, numbers, **fields), tier=E2E)


def joined(change: str) -> StoredUnit:
    """The unit an earlier plan made of groups 1, 2 and 3 of `change`."""
    return stored_unit(f"{change}/7", change=change, tier=E2E, groups=(1, 2, 3))


def test_an_unstarted_joined_unit_is_split_by_the_next_plan_and_a_started_one_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(
        tmp_path,
        monkeypatch,
        split=tagged_md(E2E, E2E, E2E),
        other=tagged_md(E2E, E2E, E2E),
        kept=tagged_md(E2E, E2E, E2E),
    )
    run.store.upsert([joined("split"), joined("other"), joined("kept")])
    run.store.set_state("kept/7", IN_REVIEW, branch="spec/kept/7", pr=9)
    for change in ("split", "other", "kept"):
        run.record(change, sizing="a-digest-of-other-ceilings")
    stored = {u.id: u for u in run.store.all()}

    # The plan that keeps the groups together is refused, and nothing is rewritten.
    refused, _ = run.run(
        capsys, "split", "--accept-unplanned", reply=answer(e2e("split/1", (1, 2, 3)))
    )
    assert refused == 1
    assert {u.id: u for u in run.store.all()} == stored

    for change in ("split", "other"):
        apart = answer(
            e2e(f"{change}/1", (1,)),
            e2e(f"{change}/2", (2,), depends_on=(f"{change}/1",)),
            e2e(f"{change}/3", (3,), depends_on=(f"{change}/2",)),
        )
        code, out = run.run(capsys, change, "--accept-unplanned", reply=apart)
        assert code == 0, out
        built = [u for u in run.store.all() if u.change == change and u.state == PLANNED]
        assert sorted(u.groups for u in built) == [(1,), (2,), (3,)]
        assert run.store.get(f"{change}/7").state == UnitState.UNPLANNED

    code, out = run.run(capsys, "kept", "--accept-unplanned")
    assert code == 0, out
    assert f"kept: kept/7, {IN_REVIEW.value}" in out
    assert run.store.get("kept/7") == stored["kept/7"]
