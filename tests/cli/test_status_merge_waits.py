"""`abk status` words a merge wait by what is missing and why the edge is a merge edge (spec:
needs-can-wait-for-a-merge): the parent not merged, the next tick to load the merge, or the kit
checkout to include it; each followed by `(merge: <reason>)`. Status changes nothing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.loaded_code import TickRecord, write_record
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import FAILED, IN_REVIEW, MERGED, PLANNED, RUNNING
from tests.conftest import make_installation, run_status
from tests.factories import commit, git, new_unit
from tests.kit_checkout import kit_at


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return make_installation(
        tmp_path, planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")}
    )


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    return UnitStore(inst.state_dir / "units.json")


def gated(store: UnitStore, uid: str, parent: str, *, merge: bool = True) -> None:
    """`uid` is planned, parked on `parent`, with `merged` on its `Needs:` line when `merge`."""
    store.set_state(uid, PLANNED, note="parked", cause=Cause.GATED)
    store.set_needs(uid, (parent,))
    if merge:
        store.set_merge_needs(uid, (parent,))


def wait_line(lines: list[str], unit: str) -> str:
    return next(line for line in lines if unit in line and "waiting for" in line)


def test_a_merge_wait_is_worded_by_what_is_missing_and_status_changes_nothing(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    kit = inst.checkouts["app"]
    head = kit_at(kit, monkeypatch)
    git(kit, "checkout", "-q", "-b", "elsewhere")
    absent = commit(kit, "absent.txt")
    git(kit, "checkout", "-q", "main")
    pulled = commit(kit, "pulled.txt")
    write_record(
        inst.state_dir,
        TickRecord(
            number=2,
            started_at=datetime.now(UTC),
            kit_repo="app",
            kit_root=str(kit),
            kit_head=head,
        ),
    )
    store.upsert(
        [
            *(new_unit(f"p{n}/1") for n in (1, 2, 3)),
            *(new_unit(f"d{n}/1", depends_on=(f"p{n}/1",)) for n in (1, 2, 3)),
            new_unit("run/1"),
            new_unit("plain/1", depends_on=("run/1",)),
        ]
    )
    store.set_state("p1/1", IN_REVIEW, pr=1)
    store.set_state("p2/1", MERGED, pr=2)
    store.set_merge_record("p2/1", merge_sha=pulled, merged_tick=2)
    store.set_state("p3/1", MERGED, pr=3)
    store.set_merge_record("p3/1", merge_sha=absent, merged_tick=2)
    store.set_state("run/1", RUNNING, branch="spec/run/1")
    for n in (1, 2, 3):
        gated(store, f"d{n}/1", f"p{n}/1")
    gated(store, "plain/1", "run/1", merge=False)
    recorded = [inst.state_dir / "units.json", inst.state_dir / "tick.json"]
    before = [path.read_bytes() for path in recorded]

    lines = run_status(inst, monkeypatch, capsys)

    reason = "(merge: the Needs: line says merged)"
    assert f"waiting for p1 group 1 to merge {reason}" in wait_line(lines, "d1/1")
    assert f"waiting for the next tick to load p2 group 1's merge {reason}" in wait_line(
        lines, "d2/1"
    )
    assert f"waiting for the kit checkout to include p3 group 1's merge {reason}" in wait_line(
        lines, "d3/1"
    )
    review = wait_line(lines, "plain/1")
    assert "waiting for run group 1" in review and "(merge:" not in review
    assert before == [path.read_bytes() for path in recorded], "status writes neither record"


def test_a_cross_repo_edge_gives_another_repository_as_its_reason(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store.upsert([new_unit("lib/1", repo="platform"), new_unit("use/1", depends_on=("lib/1",))])
    store.set_state("lib/1", IN_REVIEW, pr=1)
    gated(store, "use/1", "lib/1", merge=False)

    lines = run_status(inst, monkeypatch, capsys)

    assert "waiting for lib group 1 to merge (merge: another repository)" in wait_line(
        lines, "use/1"
    )


def test_a_failed_unit_waiting_on_a_plain_parent_says_it_resumes_after_the_fix_is_merged(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store.upsert([new_unit("fix/1"), new_unit("kid/1", depends_on=("fix/1",))])
    store.set_state("fix/1", IN_REVIEW, pr=1)
    store.set_state("kid/1", FAILED, branch="spec/kid/1", cause=Cause.FAILED)
    store.set_needs("kid/1", ("fix/1",))

    lines = run_status(inst, monkeypatch, capsys)

    [line] = [line for line in lines if "failed, waiting on" in line]
    assert "failed, waiting on fix/1" in line and "kid/1" in line
    assert (
        "waiting for fix group 1 to merge (merge: a failed unit resumes after the fix is merged)"
        in line
    )
