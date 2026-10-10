"""A pass keeps its build slots full while it runs.

The tick used to work out what was ready once, build that batch and wait for
all of it, so a parent reaching review could not start its child until every
unrelated unit in the batch had finished. These tests drive `cmd_tick` with a
builder whose completions each test controls, and look at what the pass
started, when, and how many at once.

The builder marks the store the way the real one does: `running` while it
builds, `in_review` once its PR is open, and back to `planned` when it pauses
or is held.
"""

from __future__ import annotations

import argparse
import fcntl
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.graph.checkpointer import unit_graphs_path
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import pause
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus, UnitRunner
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import (
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    UnitState,
    local_ref,
    ready_units,
)
from agent_build_kit.pipeline.usage_guard import Decision, RateLimited
from agent_build_kit.pipeline.wiring import (
    build_base_moved,
    build_may_start,
    build_upstream_incomplete,
)
from agent_build_kit.pipeline.workspaces import branch_lock
from agent_build_kit.settings import reload
from tests.conftest import make_installation
from tests.factories import git, init_repo
from tests.runtimes.selectable import SelectableRuntime, select

# How long a build waits for something the pass should make happen meanwhile.
# Long enough never to trip when the pass does it; against a pass that fixes
# its batch at the start, it is what the slow unit waits before giving up.
WAIT = 30

pytestmark = pytest.mark.usefixtures("scripted_engine")


def eventually(condition: Callable[[], bool]) -> bool:
    """Whether `condition` comes true within `WAIT`. For waiting on another
    build having *finished*, which no event it sets mid-build can say."""
    deadline = time.monotonic() + WAIT
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


@pytest.fixture(autouse=True)
def warm_unit_graphs(tmp_path: Path) -> None:
    """The unit-graph database already in WAL, so builds opening it together do
    not race to switch the journal mode (`database is locked`)."""
    with closing(sqlite3.connect(unit_graphs_path(tmp_path))) as conn:
        conn.execute("PRAGMA journal_mode=WAL")


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Everything around building stubbed: GitHub, the network, planning,
    live verification and the usage window. Tests about those replace the
    stub they need."""
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "verify_ready", lambda inst, units, **kwargs: lambda change: True)
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: [])
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    monkeypatch.setattr(
        cli, "may_start_unit", lambda r, **_: Decision(may_start=True, reason="plenty")
    )


def workspace(tmp_path: Path, *, max_concurrent: int = 4, depth_cap: int = 3) -> Installation:
    return make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        limits={
            "max_concurrent_stacks": max_concurrent,
            "stack_depth_build_cap": depth_cap,
            "max_units_in_progress": 50,  # these tests are about the other caps
        },
    )


def stored(uid: str, **overrides) -> StoredUnit:
    change, _, _ = uid.partition("/")
    defaults: dict = {
        "id": uid,
        "change": change,
        "title": f"Build {uid}",
        "repo": "app",
        "tier": "tier1",
        "depends_on": (),
        "estimated_lines": 140,
        "groups": (1,),
    }
    return StoredUnit(**{**defaults, **overrides})


def tick(inst: Installation, *, only: list[str] | None = None) -> int:
    args = argparse.Namespace(dry_run=False)
    if only is not None:
        args.only = only
    return cli.cmd_tick(args, inst)


class Builder:
    """Stands in for `build_runner`: each unit's build runs its script, if it
    has one, and ends as the script says — "open" by default."""

    def __init__(self, store: UnitStore) -> None:
        self.store = store
        self.scripts: dict[str, Callable[[], str | None]] = {}
        # Run before the build marks its unit `running`, as the real one's
        # lock, store read and usage check are.
        self.before_running: dict[str, Callable[[], object]] = {}
        # How a unit's build ends when it is not in review: the state, cause and
        # note it leaves. A unit not named here is left `planned` with its status as note.
        self.ends: dict[str, tuple[UnitState, Cause | None, str]] = {}
        self.started: list[str] = []
        self.finished: list[str] = []
        self._lock = threading.Lock()
        self._prs = 0

    def __call__(self, unit, **kwargs) -> Builder._Run:
        return Builder._Run(self)

    class _Run:
        def __init__(self, builder: Builder) -> None:
            self.builder = builder

        def run(self, unit, *, base, graph) -> RunOutcome:
            return self.builder._run(unit)

    def _run(self, unit) -> RunOutcome:
        with self._lock:
            self.started.append(unit.id)
        self.before_running.get(unit.id, lambda: None)()
        self.store.set_state(unit.id, RUNNING, branch=f"spec/{unit.id}")
        try:
            status = self.scripts.get(unit.id, lambda: None)() or "open"
        finally:
            with self._lock:
                self._prs += 1
                pr = self._prs

        if status == "open":
            self.store.set_state(unit.id, IN_REVIEW, pr=pr)
        elif unit.id in self.ends:
            state, cause, note = self.ends[unit.id]
            held_by = HOLDERS.get(cause, HeldBy.NONE) if state == HELD and cause else HeldBy.NONE
            self.store.set_state(unit.id, state, note=note, cause=cause, held_by=held_by)
        else:
            note = status if ":" in status else f"{status} before implement"
            self.store.set_state(unit.id, PLANNED, note=note)
        with self._lock:
            self.finished.append(unit.id)
        return RunOutcome(
            status=RunStatus(status.split()[0].rstrip(":")), detail=f"{status} {unit.id}", pr=pr
        )


# Who really holds a unit for each cause that ends a run `held`.
HOLDERS = {
    Cause.TOOLCHAIN: HeldBy.TOOLCHAIN,
    Cause.DEPTH: HeldBy.DEPTH,
    Cause.REVIEW_ESCALATED_CLASS: HeldBy.REVIEW,
    Cause.REVIEW_ESCALATED_DISAGREEMENT: HeldBy.REVIEW,
    Cause.NEEDS_HUMAN: HeldBy.REVIEW,
}


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    fake = Builder(UnitStore(tmp_path / "units.json"))
    monkeypatch.setattr(cli, "build_runner", fake)
    return fake


# --- 1.1 what a completion releases starts in the same pass -----------------------


def test_a_parent_reaching_review_starts_its_child_in_the_same_pass(
    builder: Builder, tmp_path: Path
) -> None:
    """A same-repo child stacks on its parent's branch, so it is ready the
    moment the parent's PR is open. It must not wait for an unrelated slow
    unit in another repo — which here holds on until the child has finished."""
    inst = workspace(tmp_path)
    builder.store.upsert(
        [
            stored("chain/1"),
            stored("chain/2", depends_on=("chain/1",)),
            stored("slow/1", repo="platform"),
        ]
    )
    builder.scripts["slow/1"] = lambda: (
        None if eventually(lambda: "chain/2" in builder.finished) else "failed"
    )

    assert tick(inst) == 0

    assert "chain/2" in builder.started, "the child waited for the next pass"
    assert builder.finished.index("chain/2") < builder.finished.index("slow/1")
    assert builder.store.get("slow/1").state == IN_REVIEW


def test_a_pass_with_one_long_build_still_refreshes_and_fills_free_slots(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Waiting only for a completion left a pass with one long build blind for
    its whole length — no poll, so no merge, comment or conflict was heard —
    and the timer cannot start another tick while this one runs."""
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("slow/1", repo="platform")])
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
    polls: list[int] = []

    def poll(inst, **kwargs) -> None:
        polls.append(1)
        if len(polls) == 2:  # something new turns up while slow/1 builds
            builder.store.upsert([stored("late/1")])

    monkeypatch.setattr(cli, "poll_all", poll)
    builder.scripts["slow/1"] = lambda: (
        None if eventually(lambda: "late/1" in builder.finished) else "failed"
    )

    assert tick(inst) == 0

    assert builder.finished.index("late/1") < builder.finished.index("slow/1")
    assert builder.store.get("slow/1").state == IN_REVIEW


MOVED_NOTE = "held before implement: its base moved from spec/a/1 to main while it built"


def _sends_back(builder: Builder, unit_id: str, *, times: int):
    """A poll that, after each time `unit_id` reaches review, sends it back for
    rework — as a conflict or a failing check does — up to `times` times."""
    sent: list[int] = []

    def poll(inst, **kwargs) -> None:
        if builder.store.get(unit_id).state == IN_REVIEW and len(sent) < times:
            sent.append(1)
            builder.store.set_state(
                unit_id,
                PLANNED,
                note="rework requested: merge conflict with its base",
                cause=Cause.REWORK,
            )

    return poll


def test_a_unit_a_poll_sends_back_is_rebuilt_in_the_same_pass(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Built once in a pass, a unit used to wait for the next pass however it
    was sent back — and the next pass could not start until this one ended."""
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("conflicted/1"), stored("slow/1", repo="platform")])
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
    monkeypatch.setattr(cli, "poll_all", _sends_back(builder, "conflicted/1", times=1))
    builder.scripts["slow/1"] = lambda: (
        None if eventually(lambda: builder.finished.count("conflicted/1") == 2) else "failed"
    )

    assert tick(inst) == 0

    assert builder.started.count("conflicted/1") == 2
    assert builder.store.get("conflicted/1").state == IN_REVIEW


def test_a_unit_that_held_itself_during_the_pass_is_started_again_in_it(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A build stops itself, "held before ...", when its base moved — which is
    what a parent's merge does to a child built on it. Left to the next pass,
    it waited out every build still running, and one slow build kept a ready
    unit idle for as long as it took."""
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("moved/1"), stored("slow/1", repo="platform")])
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
    runs: list[int] = []

    def holds_once() -> str | None:
        runs.append(1)
        return "held" if len(runs) == 1 else None

    builder.scripts["moved/1"] = holds_once
    builder.ends["moved/1"] = (PLANNED, Cause.BASE_CHANGED, MOVED_NOTE)
    builder.scripts["slow/1"] = lambda: (
        None if eventually(lambda: builder.finished.count("moved/1") == 2) else "failed"
    )

    assert tick(inst) == 0

    assert builder.started.count("moved/1") == 2
    assert builder.store.get("moved/1").state == IN_REVIEW


def test_a_unit_that_keeps_holding_itself_is_started_a_bounded_number_of_times(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pass must still end."""
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("moved/1"), stored("slow/1", repo="platform")])
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
    builder.scripts["moved/1"] = lambda: "held"
    builder.ends["moved/1"] = (PLANNED, Cause.BASE_CHANGED, MOVED_NOTE)
    builder.scripts["slow/1"] = lambda: (
        None
        if eventually(lambda: builder.started.count("moved/1") > cli.REBUILDS_PER_PASS)
        else "failed"
    )

    assert tick(inst) == 0

    assert builder.started.count("moved/1") == 1 + cli.REBUILDS_PER_PASS


def test_a_unit_sent_back_again_and_again_is_rebuilt_a_bounded_number_of_times(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pass must still end."""
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("conflicted/1"), stored("slow/1", repo="platform")])
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
    monkeypatch.setattr(cli, "poll_all", _sends_back(builder, "conflicted/1", times=100))
    builder.scripts["slow/1"] = lambda: (
        None
        if eventually(lambda: builder.started.count("conflicted/1") > cli.REBUILDS_PER_PASS)
        else "failed"
    )

    assert tick(inst) == 0

    assert builder.started.count("conflicted/1") == 1 + cli.REBUILDS_PER_PASS


def test_a_unit_set_back_to_planned_during_the_pass_is_started_by_it(
    builder: Builder, tmp_path: Path
) -> None:
    """Setting a unit back to `planned` is the documented recovery once the
    cause of its failure is fixed; with slots free, the pass in flight picks
    it up rather than leaving it for the next one."""
    inst = workspace(tmp_path)
    builder.store.upsert([stored("feature/1"), stored("feature/2")])
    builder.store.set_state("feature/2", UnitState.FAILED)

    def requeue() -> None:
        builder.store.set_state("feature/2", PLANNED, note="requeued by hand")

    builder.scripts["feature/1"] = requeue

    assert tick(inst) == 0

    assert builder.started == ["feature/1", "feature/2"]
    assert builder.store.get("feature/2").state == IN_REVIEW


# --- 1.2 the slots stay full, and the caps still hold ------------------------------


def test_a_long_running_unit_does_not_keep_the_other_slots_idle(
    builder: Builder, tmp_path: Path
) -> None:
    """Two slots, one taken by a slow build: the other works through every
    remaining unit while the slow one continues."""
    inst = workspace(tmp_path, max_concurrent=2)
    quick = ["quick/1", "quick/2", "quick/3"]
    builder.store.upsert([stored("slow/1", repo="platform"), *(stored(uid) for uid in quick)])
    builder.scripts["slow/1"] = lambda: (
        None if eventually(lambda: all(uid in builder.finished for uid in quick)) else "failed"
    )

    assert tick(inst) == 0

    assert sorted(builder.started) == sorted(["slow/1", *quick])
    assert builder.finished[-1] == "slow/1"
    assert builder.store.get("slow/1").state == IN_REVIEW


def test_no_more_than_the_concurrency_cap_build_at_once(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-evaluating on every completion must not overshoot the cap: a unit
    just handed out is not `running` in the store until its build says so.

    Measured where units are handed out rather than where they build: the
    pool has only as many workers as the cap, so an overshoot would queue
    there and never show as more than two building. Here the second unit is
    handed out but not yet `running` when the first finishes, and the pass
    evaluates again in that gap."""
    inst = workspace(tmp_path, max_concurrent=2)
    ids = [f"many/{n}" for n in range(1, 7)]
    builder.store.upsert(
        [stored(uid, repo="platform" if n % 2 else "app") for n, uid in enumerate(ids)]
    )
    go = threading.Event()
    for uid in ids[1:]:
        builder.before_running[uid] = lambda: go.wait(WAIT)

    handed_out = 0
    at_each_evaluation: list[int] = []

    def evaluate(graph, **kwargs):
        nonlocal handed_out
        ready = ready_units(graph, **kwargs)
        if kwargs["max_concurrent"] > inst.max_concurrent_stacks:
            return ready  # the look at who is only waiting for a slot hands nothing out
        in_flight = handed_out - len(builder.finished)
        at_each_evaluation.append(in_flight + len(ready))
        handed_out += len(ready)
        if len(at_each_evaluation) > 1:
            go.set()  # once the first re-evaluation has looked into the gap
        return ready

    monkeypatch.setattr(cli, "ready_units", evaluate)

    assert tick(inst) == 0

    assert sorted(builder.started) == sorted(ids)
    assert len(at_each_evaluation) > 2
    assert max(at_each_evaluation) <= 2, at_each_evaluation


def test_a_chain_past_the_depth_cap_is_still_held_back(builder: Builder, tmp_path: Path) -> None:
    """Re-evaluating builds a chain link by link in one pass — until it has
    run as far ahead of review as the depth cap allows, where it stops."""
    inst = workspace(tmp_path, depth_cap=2)
    builder.store.upsert(
        [
            stored("chain/1"),
            stored("chain/2", depends_on=("chain/1",)),
            stored("chain/3", depends_on=("chain/2",)),
        ]
    )

    assert tick(inst) == 0

    assert builder.started == ["chain/1", "chain/2"]
    assert builder.store.get("chain/3").state == PLANNED


def test_no_unit_is_started_twice_in_one_pass(builder: Builder, tmp_path: Path) -> None:
    """A held build leaves its unit `planned`, so the store alone would hand
    it out again on the next evaluation. The pass remembers what it started."""
    inst = workspace(tmp_path, max_concurrent=1)
    builder.store.upsert([stored("feature/1"), stored("feature/2")])
    builder.scripts["feature/1"] = lambda: "held"

    assert tick(inst) == 0

    assert builder.started == ["feature/1", "feature/2"]
    assert builder.store.get("feature/1").state == PLANNED


# --- 1.3 stopping, and --only ------------------------------------------------------


def test_a_build_the_model_refused_ends_scheduling(builder: Builder, tmp_path: Path) -> None:
    """One slot: the first unit opens its PR and the second starts in the same
    pass; the model refuses the second, and the third is not started."""
    inst = workspace(tmp_path, max_concurrent=1)
    builder.store.upsert([stored("feature/1"), stored("feature/2"), stored("feature/3")])

    def refused() -> None:
        pause.pause_until(
            datetime.now(UTC) + timedelta(hours=1),
            reason="the model refused",
            marker=tmp_path / "paused.json",
            kind="rate_limit",
        )

    builder.scripts["feature/2"] = refused

    assert tick(inst) == 0

    assert builder.started == ["feature/1", "feature/2"]
    assert builder.store.get("feature/3").state == PLANNED


def test_a_build_that_pauses_waits_for_the_ramp_not_the_reset(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A unit that stops between steps records the guard's own answer to when,
    which counts the ramp towards the reset."""
    inst = workspace(tmp_path, max_concurrent=1)
    builder.store.upsert([stored("feature/1")])
    builder.scripts["feature/1"] = lambda: "paused"
    ramp = datetime.now(UTC) + timedelta(minutes=35)
    answers = iter([Decision(may_start=True, reason="room")])
    monkeypatch.setattr(
        cli,
        "may_start_unit",
        lambda r: next(answers, Decision(may_start=False, reason="session", resume_at=ramp)),
    )

    assert tick(inst) == 0

    state = pause.is_paused(tmp_path / "paused.json")
    assert state is not None
    assert state.until == ramp + pause.RESUME_GRACE


def test_a_rate_limit_pause_recorded_by_a_build_still_running_ends_scheduling(
    builder: Builder, tmp_path: Path
) -> None:
    """Two slots. The slow build records a pause and keeps going; the quick
    one then completes normally, reporting nothing wrong. The marker alone
    stops the pass from starting the next unit, and the slow build is still
    awaited."""
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("slow/1", repo="platform"), stored("quick/1"), stored("later/1")])
    marker = tmp_path / "paused.json"

    def slow() -> str | None:
        pause.pause_until(
            datetime.now(UTC) + timedelta(hours=1),
            reason="the model refused",
            marker=marker,
            kind="rate_limit",
        )
        return None if eventually(lambda: "quick/1" in builder.finished) else "failed"

    builder.scripts["slow/1"] = slow
    builder.scripts["quick/1"] = lambda: None if eventually(marker.exists) else "failed"

    assert tick(inst) == 0

    assert sorted(builder.started) == ["quick/1", "slow/1"]
    assert builder.finished[-1] == "slow/1"
    assert builder.store.get("slow/1").state == IN_REVIEW
    assert builder.store.get("later/1").state == PLANNED


def test_stopping_still_awaits_the_builds_in_flight(builder: Builder, tmp_path: Path) -> None:
    """What stops is submission. A build already running checks the guard
    itself, and killing it would leave its work uncommitted, so the pass
    waits for it to finish before returning."""
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert(
        [
            stored("quick/1"),
            stored("slow/1", repo="platform"),
            stored("stops/1"),
            stored("later/1"),
        ]
    )

    def refused() -> None:
        pause.pause_until(
            datetime.now(UTC) + timedelta(hours=1),
            reason="the model refused",
            marker=tmp_path / "paused.json",
            kind="rate_limit",
        )

    builder.scripts["stops/1"] = refused
    builder.scripts["slow/1"] = lambda: (
        None if eventually((tmp_path / "paused.json").exists) else "failed"
    )

    assert tick(inst) == 0

    assert sorted(builder.started) == ["quick/1", "slow/1", "stops/1"]
    assert "slow/1" in builder.finished
    assert builder.store.get("slow/1").state == IN_REVIEW
    assert builder.store.get("later/1").state == PLANNED


def test_only_narrows_every_evaluation(builder: Builder, tmp_path: Path) -> None:
    """Narrowed to two links of a chain, the pass builds both — the second
    once the first unblocks it — and not the third, which the second's
    completion unblocks in turn."""
    inst = workspace(tmp_path)
    builder.store.upsert(
        [
            stored("chain/1"),
            stored("chain/2", depends_on=("chain/1",)),
            stored("chain/3", depends_on=("chain/2",)),
        ]
    )

    assert tick(inst, only=["chain/1", "chain/2"]) == 0

    assert builder.started == ["chain/1", "chain/2"]
    assert builder.store.get("chain/3").state == PLANNED


# --- 1.4 refreshing from the code host, and planning once --------------------------


def test_each_evaluation_refreshes_from_the_code_host_first(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = workspace(tmp_path, max_concurrent=1)
    builder.store.upsert([stored("feature/1"), stored("feature/2")])
    order: list[str] = []
    monkeypatch.setattr(cli, "fetch_all", lambda inst: order.append("fetch"))
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: order.append("poll"))

    def evaluate(graph, **kwargs):
        if kwargs["max_concurrent"] <= inst.max_concurrent_stacks:
            order.append("evaluate")
        return ready_units(graph, **kwargs)

    monkeypatch.setattr(cli, "ready_units", evaluate)

    assert tick(inst) == 0

    assert builder.started == ["feature/1", "feature/2"]
    evaluations = [n for n, step in enumerate(order) if step == "evaluate"]
    assert len(evaluations) >= 2
    assert all(n > 1 and order[n - 2 : n] == ["fetch", "poll"] for n in evaluations), order


def test_a_dependency_merging_mid_pass_releases_its_dependent(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cross-repo dependency must have merged, and only a refresh reveals
    that it has. Here it merges while another unit builds."""
    inst = workspace(tmp_path)
    builder.store.upsert(
        [
            stored("base/1", repo="platform"),
            stored("uses/1", depends_on=("base/1",)),
            stored("other/1"),
        ]
    )
    builder.store.set_state("base/1", IN_REVIEW, pr=7)
    merged_meanwhile = threading.Event()

    def poll(inst, *, store):
        if merged_meanwhile.is_set():
            store.set_state("base/1", MERGED, pr=7)

    monkeypatch.setattr(cli, "poll_all", poll)
    builder.scripts["other/1"] = merged_meanwhile.set

    assert tick(inst) == 0

    assert builder.started == ["other/1", "uses/1"]


@pytest.mark.parametrize(
    ("step", "skipped"), [("poll_all", "poll skipped"), ("fetch_all", "fetch skipped")]
)
def test_a_failing_refresh_is_logged_and_the_pass_continues(
    builder: Builder,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    step: str,
    skipped: str,
) -> None:
    """The first refresh, at the top of the tick, succeeds; the one after a
    completion raises."""
    inst = workspace(tmp_path, max_concurrent=1)
    builder.store.upsert([stored("feature/1"), stored("feature/2")])
    calls: list[int] = []

    def refresh(inst, **kwargs):
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError("github unreachable")

    monkeypatch.setattr(cli, step, refresh)

    assert tick(inst) == 0

    assert builder.started == ["feature/1", "feature/2"]
    assert len(calls) >= 2
    out = capsys.readouterr().out
    assert skipped in out
    assert "github unreachable" in out


def test_a_repo_refused_mid_pass_is_not_built_and_the_pass_fails(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only `platform` lacks a commit identity, and nothing in it is ready at
    the top of the tick. `app/1`'s completion releases a platform unit — its
    dependency merges meanwhile — which the pass refuses to start. The build
    already in flight still finishes, and the tick reports the refusal."""
    inst = workspace(tmp_path)
    builder.store.upsert(
        [
            stored("base/1"),
            stored("uses/1", repo="platform", depends_on=("base/1",)),
            stored("app/1"),
            stored("slow/1"),
        ]
    )
    builder.store.set_state("base/1", IN_REVIEW, pr=7)
    refused = threading.Event()

    def has_identity(inst, repo: str) -> bool:
        if repo == "platform":
            refused.set()
            return False
        return True

    def poll(inst, *, store):
        if "app/1" in builder.finished:
            store.set_state("base/1", MERGED, pr=7)

    monkeypatch.setattr(cli, "has_identity", has_identity)
    monkeypatch.setattr(cli, "poll_all", poll)
    builder.scripts["slow/1"] = lambda: None if refused.wait(WAIT) else "failed"

    assert tick(inst) == 1

    assert "uses/1" not in builder.started
    assert builder.store.get("uses/1").state == PLANNED
    assert "slow/1" in builder.finished
    assert builder.store.get("slow/1").state == IN_REVIEW


def test_planning_happens_in_every_round_of_the_pass(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A change written during a pass is planned by its next refresh; a change
    already planned costs no model call (see `test_round`)."""
    inst = workspace(tmp_path, max_concurrent=1)
    builder.store.upsert([stored("feature/1"), stored("feature/2"), stored("feature/3")])
    plans: list[int] = []
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: plans.append(1))

    assert tick(inst) == 0

    assert builder.started == ["feature/1", "feature/2", "feature/3"]
    assert len(plans) == 4, "the tick's round, then one after each of three completions"


# --- a refresh mid-pass leaves the builds in flight alone --------------------------

# Captured before the autouse fixture stubs it: this test needs the real
# dispatch wiring, with only GitHub and git faked beneath it.
REAL_POLL_ALL = cli.poll_all


@pytest.mark.parametrize("step", ["delete_branch", "remove_worktree", "move", "push"])
def test_an_event_handler_writes_to_a_repo_only_in_its_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    """A poll now runs while builds do, and a build's worktree add and push
    take the repo's turn because git's own locks fail rather than wait. So
    each handler step that writes to the same `.git` takes that turn too."""
    inst = workspace(tmp_path)
    lock = tmp_path / "locks" / "repo-app.lock"
    held: list[bool] = []

    def records_the_turn(*args, **kwargs) -> None:
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                held.append(True)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
                held.append(False)

    monkeypatch.setattr(cli, "resolved_move", records_the_turn)
    monkeypatch.setattr(cli, "push_with_lease", records_the_turn)
    monkeypatch.setattr(cli, "build_delete_branch", lambda repos: records_the_turn)
    monkeypatch.setattr(cli, "build_remove_worktree", lambda repos, root: records_the_turn)
    wired: dict = {}
    monkeypatch.setattr(cli, "build_restack", lambda **kw: wired.update(kw))
    monkeypatch.setattr(cli, "build_dispatch", lambda store, **kw: wired.update(kw))
    monkeypatch.setattr(cli, "Poller", lambda **kw: argparse.Namespace(poll=lambda: None))

    REAL_POLL_ALL(inst, store=UnitStore(tmp_path / "units.json"))

    if step in ("move", "push"):
        wired[step](inst.checkouts["app"], "spec/feature/2", new_base="main")
    else:
        wired[step]("app", "spec/feature/1")
    assert held == [True], f"{step} ran outside the repo's turn"


def test_a_poll_hands_each_event_to_the_unit_in_the_repo_it_polled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One dispatch serves every repo's poller, and a poller reports a bare
    number. Both repos have a pull request 5 here; only the repo being polled
    says whose it is, and its name is the unit's, not the forge's slug."""
    inst = workspace(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored("feature/1", repo="platform"), stored("add-marker/1")])
    store.set_state("feature/1", IN_REVIEW, pr=5, branch="spec/feature/1")
    store.set_state("add-marker/1", IN_REVIEW, pr=5, branch="spec/add-marker/1")

    class OneMerge:
        """Reports pull request 5 merged, in the one repo where it did."""

        def __init__(self, *, repo: str, dispatch, **kwargs) -> None:
            self.repo, self.dispatch = repo, dispatch

        def poll(self) -> None:
            if self.repo == "example/app":
                self.dispatch("merged", 5, pull={})

    monkeypatch.setattr(cli, "Poller", OneMerge)
    monkeypatch.setattr(cli, "build_restack", lambda **kw: lambda **a: None)
    monkeypatch.setattr(cli, "build_retarget", lambda: lambda unit, base: None)
    monkeypatch.setattr(cli, "build_remove_worktree", lambda *a, **k: lambda repo, branch: None)
    monkeypatch.setattr(cli, "build_delete_branch", lambda *a, **k: lambda repo, branch: None)

    REAL_POLL_ALL(inst, store=store)

    assert store.get("add-marker/1").state == MERGED
    assert store.get("feature/1").state == IN_REVIEW


@pytest.mark.parametrize("step", ["test tasks", "remaining tasks"], ids=["tests", "implement"])
def test_a_parent_merging_while_its_child_builds_moves_the_child_before_its_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    """The refresh after another unit's completion hears that the parent
    merged while its same-repo child is still building. It records the merge
    but leaves the child's branch alone — restacking would rebase the tree the
    agent is writing to. The child's build sees its base moved and stops
    before pushing; the same pass starts it again, restacks it onto the trunk and
    opens its PR there, not against the merged branch.

    Git is faked as git behaves: a deleted branch counts no commits after it.
    The child's build started on the parent's local branch, so a merge heard
    during its implement step that deleted that branch would leave it
    counting none of its own, and fail rather than be held."""
    inst = workspace(tmp_path, max_concurrent=2)
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            stored("chain/1"),
            stored("chain/2", depends_on=("chain/1",)),
            stored("other/1", repo="platform"),
        ]
    )
    store.set_state("chain/1", IN_REVIEW, pr=7, branch="spec/chain/1")

    merged = threading.Event()

    class GitHub:
        """Reports chain/1's PR merged on the first poll after other/1 is done."""

        def __init__(self, *, repo: str, dispatch, **kwargs) -> None:
            self.repo, self.dispatch = repo, dispatch

        def poll(self) -> None:
            if self.repo == "example/app" and not merged.is_set():
                if store.get("other/1").state == IN_REVIEW:
                    self.dispatch("merged", 7, pull={})
                    merged.set()

    restacked_by_merge: list[str] = []
    monkeypatch.setattr(cli, "poll_all", REAL_POLL_ALL)
    monkeypatch.setattr(cli, "Poller", GitHub)
    monkeypatch.setattr(
        cli, "build_restack", lambda **kw: lambda **a: restacked_by_merge.append(a["child"].id)
    )
    monkeypatch.setattr(cli, "build_retarget", lambda: lambda unit, base: None)
    monkeypatch.setattr(cli, "build_remove_worktree", lambda *a, **k: lambda repo, branch: None)
    deleted: set[str] = set()
    monkeypatch.setattr(
        cli, "build_delete_branch", lambda *a, **k: lambda repo, branch: deleted.add(branch)
    )

    opened: list[tuple[str, str]] = []
    moved_onto: list[tuple[str, str]] = []
    commits: dict[str, int] = {}

    def branch_commits(unit_id: str, ref: str) -> int:
        # `git rev-list --count <deleted>..HEAD`, run with check=False.
        return 0 if ref in deleted else commits.get(unit_id, 0)

    def runner(unit, *, store: UnitStore, installation, log, **kwargs) -> UnitRunner:
        def claude(prompt: str, *, cwd: Path, **session) -> str:
            if unit.id == "chain/2" and step in prompt:
                # Still at this step when the merge is heard.
                assert merged.wait(WAIT), "the refresh never reported the merge"
            return ""

        def commit(message: str, *, cwd: Path, base: str = "") -> int:
            commits[unit.id] = commits.get(unit.id, 0) + 1
            return 1

        def open_pr(u, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
            opened.append((u.id, base))
            return 20 + len(opened)

        return UnitRunner(
            store=store,
            planning_repo=tmp_path / "planning",
            worktree=lambda u, base: tmp_path / "trees" / u.id,
            may_start=lambda: (True, ""),
            run=claude,
            run_review=lambda *, cwd, context="", **session: '{"approved": true}',
            run_rework_review=lambda *, cwd, context="", **session: '{"approved": true}',
            commit=commit,
            branch_commits=lambda tree, ref: branch_commits(unit.id, ref),
            head=lambda tree: f"{unit.id}@{commits.get(unit.id, 0)}",
            upstream_incomplete=build_upstream_incomplete(store),
            base_moved=build_base_moved(store),
            restack_onto=lambda *, tree, branch, base, unit, resolve=True: moved_onto.append(
                (unit.id, base)
            ),
            run_tier1=lambda *, cwd, base, whole_repo=False: (True, ""),
            run_tier2=lambda *, cwd: (True, ""),
            push=lambda branch, *, cwd: "pushed",
            open_pr=open_pr,
            post_status=lambda sha, ok: None,
        )

    monkeypatch.setattr(cli, "build_runner", runner)

    assert tick(inst) == 0

    assert store.get("chain/1").state == MERGED
    assert restacked_by_merge == [], "the merge rebased the tree a build was using"
    assert ("chain/2", "spec/chain/1") not in opened, "its PR was opened on the merged branch"
    # Held once, when its base moved, then started again in the same pass: the
    # restack on resume puts it on the trunk, so its PR opens there.
    assert [base for unit_id, base in opened if unit_id == "chain/2"] == ["main"], opened
    assert {base for unit_id, base in moved_onto if unit_id == "chain/2"} == {local_ref("main")}
    assert ("chain/2", "main") in opened
    assert store.get("chain/2").state == IN_REVIEW


@pytest.mark.parametrize(
    ("limits", "expected"),
    [
        ({"stack_depth_build_cap": 5, "stack_depth_rebase_cap": 2}, 2),
        ({"stack_depth_build_cap": 5}, 5),
    ],
    ids=["rebase cap set", "defaults to the build cap"],
)
def test_the_rebase_cap_reaches_the_merge_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limits: dict, expected: int
) -> None:
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        limits=limits,
    )
    wired: dict = {}
    monkeypatch.setattr(cli, "build_restack", lambda **kw: None)
    monkeypatch.setattr(cli, "build_dispatch", lambda store, **kw: wired.update(kw))
    monkeypatch.setattr(cli, "Poller", lambda **kw: argparse.Namespace(poll=lambda: None))

    REAL_POLL_ALL(inst, store=UnitStore(tmp_path / "units.json"))

    assert wired["rebase_cap"] == expected


# --- limit on units in progress ----------------------------------------------------


def limit_workspace(tmp_path: Path, limit: int) -> Installation:
    return make_installation(
        tmp_path,
        planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees")),
        limits=dict(max_units_in_progress=limit),
    )


def open_pr(builder: Builder, uid: str, pr: int, **kw) -> None:
    builder.store.upsert([stored(uid, **kw)])
    builder.store.set_state(uid, IN_REVIEW, pr=pr, branch=f"spec/{uid}")


def test_a_full_queue_starts_nothing_and_says_so(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = limit_workspace(tmp_path, 2)
    open_pr(builder, "one/1", 11)
    open_pr(builder, "two/1", 12, repo="platform")
    open_pr(builder, "three/1", 13)
    builder.store.upsert([stored("new/1")])

    assert tick(inst) == 0

    out = capsys.readouterr().out
    assert builder.started == []
    assert builder.store.get("new/1").state == PLANNED
    assert "nothing ready" not in out
    assert "3 units in progress, limit 2" in out
    assert "3 in review" in out


def test_a_failed_unit_is_named_among_those_holding_the_places(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = limit_workspace(tmp_path, 2)
    open_pr(builder, "one/1", 11)
    builder.store.upsert([stored("broke/1")])
    builder.store.set_state("broke/1", UnitState.FAILED)
    builder.store.upsert([stored("new/1")])

    assert tick(inst) == 0

    out = capsys.readouterr().out
    assert builder.started == []
    assert "2 units in progress, limit 2" in out
    assert "1 failed" in out


def test_one_short_of_the_limit_starts_one_new_unit_not_all(
    builder: Builder, tmp_path: Path
) -> None:
    inst = limit_workspace(tmp_path, 2)
    open_pr(builder, "one/1", 11)
    builder.store.upsert([stored("new/1"), stored("new/2")])

    assert tick(inst) == 0

    assert builder.started == ["new/1"]


def test_an_idle_pipeline_still_says_nothing_is_ready(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = limit_workspace(tmp_path, 2)
    open_pr(builder, "one/1", 11)

    assert tick(inst) == 0

    out = capsys.readouterr().out
    assert "nothing ready to build" in out
    assert "units in progress, limit" not in out


def test_the_reason_nothing_started_names_a_failed_prerequisite_with_units_waiting(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = limit_workspace(tmp_path, 9)
    builder.store.upsert([stored("base/1"), stored("one/1", depends_on=("base/1",))])
    builder.store.set_state("base/1", UnitState.FAILED)

    assert tick(inst) == 0

    out = capsys.readouterr().out
    assert builder.started == []
    reason = next(line for line in out.splitlines() if "base/1" in line and "requeue" in line)
    assert "1 unit waiting" in reason
    assert "nothing ready to build" not in out


def test_the_start_log_names_the_waiter_whose_age_put_a_unit_first(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = limit_workspace(tmp_path, 9)
    builder.store.upsert(
        [stored("old/1", depends_on=("base/1",)), stored("newer/1"), stored("base/1")]
    )

    assert tick(inst) == 0

    out = capsys.readouterr().out
    assert "base/1 starts ahead of newer/1: old/1 waits on it" in out


def test_the_start_log_names_the_waiter_when_the_limit_leaves_one_place(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = limit_workspace(tmp_path, 1)
    builder.store.upsert(
        [stored("old/1", depends_on=("base/1",)), stored("newer/1"), stored("base/1")]
    )

    assert tick(inst) == 0

    out = capsys.readouterr().out
    assert builder.started == ["base/1"]
    assert "base/1 starts ahead of newer/1: old/1 waits on it" in out


def test_a_rework_runs_and_reaches_review_at_the_limit(builder: Builder, tmp_path: Path) -> None:
    inst = limit_workspace(tmp_path, 2)
    open_pr(builder, "one/1", 11)
    open_pr(builder, "two/1", 12)
    builder.store.set_state("two/1", PLANNED, pr=12)
    builder.store.upsert([stored("new/1")])

    assert tick(inst) == 0

    assert builder.started == ["two/1"]
    assert builder.store.get("two/1").state == IN_REVIEW
    assert builder.store.get("new/1").state == PLANNED


def test_a_merge_lets_the_waiting_unit_start(builder: Builder, tmp_path: Path) -> None:
    inst = limit_workspace(tmp_path, 2)
    open_pr(builder, "one/1", 11)
    open_pr(builder, "two/1", 12)
    builder.store.upsert([stored("new/1")])
    assert tick(inst) == 0
    assert builder.started == []

    builder.store.set_state("one/1", MERGED, pr=11)

    assert tick(inst) == 0
    assert builder.started == ["new/1"]


def test_the_limit_is_handed_to_the_readiness_rules(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = limit_workspace(tmp_path, 3)
    builder.store.upsert([stored("new/1")])
    seen: list[tuple[object, list[str]]] = []

    def evaluate(graph, **kwargs):
        chosen = ready_units(graph, **kwargs)
        seen.append((kwargs.get("max_units_in_progress"), [unit.id for unit in chosen]))
        return chosen

    monkeypatch.setattr(cli, "ready_units", evaluate)

    assert tick(inst) == 0

    # The call that decides what starts carries the limit; reports may not.
    assert (3, ["new/1"]) in seen
    assert builder.started == ["new/1"]


# --- a runtime with no usage window is not held by one ----------------------------


@pytest.fixture
def on_demand(monkeypatch: pytest.MonkeyPatch):
    """`ABK_RUNTIME` names a runtime that has no usage window."""
    select(monkeypatch, SelectableRuntime("on-demand"))
    monkeypatch.setenv("ABK_RUNTIME", "on-demand")
    reload(None)
    yield
    monkeypatch.delenv("ABK_RUNTIME")
    reload(None)


def refusing_usage(monkeypatch: pytest.MonkeyPatch, asked: list[str]) -> None:
    """A reading and a guard that would refuse, noting that they were asked."""
    monkeypatch.setattr(cli, "current_usage", lambda: asked.append("usage"))
    monkeypatch.setattr(
        cli, "may_start_unit", lambda r, **_: Decision(may_start=False, reason="session at 88%")
    )


def test_a_runtime_without_a_usage_window_builds_past_a_refusing_guard(
    builder: Builder,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    on_demand,
) -> None:
    asked: list[str] = []
    refusing_usage(monkeypatch, asked)
    builder.store.upsert([stored("feature/1")])

    assert tick(workspace(tmp_path)) == 0

    assert builder.started == ["feature/1"]
    assert asked == []
    assert capsys.readouterr().out.count("has no usage window") == 1


def test_a_runtime_with_a_usage_window_still_pauses_on_a_refusing_guard(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refusing_usage(monkeypatch, [])
    builder.store.upsert([stored("feature/1")])

    assert tick(workspace(tmp_path)) == 0

    assert builder.started == []


def test_the_step_checkpoint_skips_the_usage_read_for_a_runtime_without_a_window(
    on_demand,
) -> None:
    allowed, _ = build_may_start(usage=lambda: pytest.fail("read the usage window"))()

    assert allowed


def test_status_reads_no_usage_window_for_a_runtime_without_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    on_demand,
) -> None:
    monkeypatch.setattr(cli, "current_usage", lambda: pytest.fail("read the usage window"))

    assert cli.cmd_status(argparse.Namespace(), workspace(tmp_path)) == 0

    assert "usage: runtime on-demand has no usage window" in capsys.readouterr().out


def test_a_rate_limit_without_a_reset_pauses_the_default_length_without_a_usage_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, on_demand
) -> None:
    """No window to ask: the pause is the default length, not one taken from
    a reading of another runtime's window."""
    inst = workspace(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored("feature/1")])
    monkeypatch.setattr(
        cli, "current_usage", lambda: pytest.fail("read a usage window the runtime lacks")
    )

    class Refusing:
        def run(self, unit, *, base, graph):
            raise RateLimited("out of room", resets_at=None)

    monkeypatch.setattr(cli, "build_runner", lambda unit, **kw: Refusing())

    assert cli.build_unit(inst, store.get("feature/1"), store=store) is False

    state = pause.is_paused(tmp_path / "paused.json")
    assert state is not None
    assert state.until <= datetime.now(UTC) + pause.UNKNOWN_RETRY


# --- a stranded unit is reclaimed before the usage check --------------------------


def test_a_unit_no_run_holds_is_planned_after_a_tick_that_pauses(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refusing_usage(monkeypatch, [])
    builder.store.upsert([stored("feature/1"), stored("feature/2")])
    builder.store.set_state("feature/1", RUNNING, branch="spec/feature/1")

    assert tick(workspace(tmp_path)) == 0

    assert builder.store.get("feature/1").state == PLANNED
    assert builder.started == [], "the pause still starts nothing"


def test_a_unit_a_live_process_holds_stays_running_through_a_pause(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refusing_usage(monkeypatch, [])
    inst = workspace(tmp_path)
    builder.store.upsert([stored("feature/1")])
    builder.store.set_state("feature/1", RUNNING, branch="spec/feature/1")

    with branch_lock("spec/feature/1", root=inst.state_dir / "locks"):
        assert tick(inst) == 0

    assert builder.store.get("feature/1").state == RUNNING
    assert builder.started == []


def test_a_unit_with_a_thread_to_resume_stays_running_through_a_pause(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Planned again, it would drop out of `resumable_units`, which only
    picks up the running."""
    refusing_usage(monkeypatch, [])
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: True)
    builder.store.upsert([stored("feature/1")])
    builder.store.set_state("feature/1", RUNNING, branch="spec/feature/1")

    assert tick(workspace(tmp_path)) == 0

    assert builder.store.get("feature/1").state == RUNNING


def test_a_pause_with_nothing_stranded_leaves_the_store_as_it_was(
    builder: Builder,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    refusing_usage(monkeypatch, [])
    builder.store.upsert([stored("feature/1"), stored("feature/2")])
    builder.store.set_state("feature/2", IN_REVIEW, pr=2, branch="spec/feature/2")
    before = builder.store.all()

    assert tick(workspace(tmp_path)) == 0

    assert builder.store.all() == before
    assert "session at 88%" in capsys.readouterr().out


# --- a unit is let back in by its cause, never by the wording of its note --------------


def _ends_and_waits(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, end, *, readmitted: bool
) -> None:
    """Build `sent/1`, which ends as `end` says, beside a slow unit that keeps the
    pass going for several refreshes — or, when `readmitted`, until `sent/1` has
    been started a second time."""
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("sent/1"), stored("slow/1", repo="platform")])
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
    runs: list[int] = []

    def ends_once() -> str | None:
        # Held the first time only, so a readmitted unit goes on to review and
        # the count of starts is exact rather than the pass's rebuild limit.
        runs.append(1)
        return "held" if len(runs) == 1 else None

    builder.scripts["sent/1"] = ends_once
    builder.ends["sent/1"] = end

    def slow() -> str | None:
        if not readmitted:
            time.sleep(0.4)  # several refreshes, in which a readmission would show
            return None
        return None if eventually(lambda: builder.started.count("sent/1") == 2) else "failed"

    builder.scripts["slow/1"] = slow

    assert tick(inst) == 0


@pytest.mark.parametrize(
    "note",
    [
        MOVED_NOTE,
        "base moved before its push: tier 1 failed on main",
        "base gone before its pull request: base branch spec/a/1 does not exist",
        "moving onto main needed resolution",
        "quite different words",
    ],
)
def test_a_unit_held_for_a_moved_base_is_let_back_in_whatever_its_note_says(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, note: str
) -> None:
    _ends_and_waits(
        builder, tmp_path, monkeypatch, (PLANNED, Cause.BASE_CHANGED, note), readmitted=True
    )

    assert builder.started.count("sent/1") == 2


def test_a_unit_sent_back_for_rework_is_let_back_in_whatever_its_note_says(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ends_and_waits(
        builder, tmp_path, monkeypatch, (PLANNED, Cause.REWORK, "reworking"), readmitted=True
    )

    assert builder.started.count("sent/1") == 2


@pytest.mark.parametrize(
    "cause",
    [
        Cause.UPSTREAM_WENT_BACK,
        Cause.USAGE,
        Cause.REQUEUED,
        Cause.RESTACK_CONFLICT,
        Cause.RESTACK_DEFERRED,
    ],
)
def test_a_planned_unit_stopped_for_any_other_cause_waits_for_the_next_pass_and_the_log_says_why(
    builder: Builder,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cause: Cause,
) -> None:
    """Even with the wording that used to readmit: a rerun would meet the same cause."""
    _ends_and_waits(
        builder,
        tmp_path,
        monkeypatch,
        (PLANNED, cause, "rework requested: " + MOVED_NOTE),
        readmitted=False,
    )

    assert builder.started.count("sent/1") == 1
    out = capsys.readouterr()
    assert cause.value in out.out + out.err, "the skip is logged with its cause"


@pytest.mark.parametrize(
    "cause",
    [
        Cause.TOOLCHAIN,
        Cause.DEPTH,
        Cause.REVIEW_ESCALATED_CLASS,
        Cause.REVIEW_ESCALATED_DISAGREEMENT,
        Cause.NEEDS_HUMAN,
    ],
)
def test_a_held_unit_is_not_let_back_in_whatever_its_note_says(
    builder: Builder,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cause: Cause,
) -> None:
    _ends_and_waits(
        builder,
        tmp_path,
        monkeypatch,
        (HELD, cause, "rework requested: " + MOVED_NOTE),
        readmitted=False,
    )

    assert builder.started.count("sent/1") == 1
    assert builder.store.get("sent/1").state == HELD
    out = capsys.readouterr()
    assert cause.value in out.out + out.err, "the skip is logged with its cause"


@pytest.mark.parametrize(
    "note",
    [MOVED_NOTE, "rework requested: merge conflict with its base", "held before review: x"],
)
def test_a_unit_whose_entry_has_no_cause_is_not_let_back_in_by_its_note_and_nothing_is_logged(
    builder: Builder,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    note: str,
) -> None:
    """The next pass takes it; the pass says nothing special about it."""
    _ends_and_waits(builder, tmp_path, monkeypatch, (PLANNED, None, note), readmitted=False)

    assert builder.started.count("sent/1") == 1
    out = capsys.readouterr()
    assert "sent/1: not started again" not in out.out + out.err
    assert "no recorded cause" not in out.out + out.err


def test_a_unit_stopped_for_a_cause_this_release_does_not_know_reads_as_no_cause(
    builder: Builder,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Written by a newer release: not readmitted, and not logged as anything special."""
    newer: Any = SimpleNamespace(value="from-a-newer-release")

    _ends_and_waits(builder, tmp_path, monkeypatch, (PLANNED, newer, "x"), readmitted=False)

    assert builder.store.get("sent/1").cause is None
    assert builder.started.count("sent/1") == 1
    out = capsys.readouterr()
    assert "sent/1: not started again" not in out.out + out.err
    assert "no recorded cause" not in out.out + out.err


# --- the build's own checks name the cause they found ----------------------------------


def test_a_parent_that_went_back_is_reported_with_the_upstream_cause(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored("a/1"), stored("a/2", depends_on=("a/1",))])
    store.set_state("a/1", PLANNED)

    found = build_upstream_incomplete(store)(store.get("a/2"))

    assert found is not None
    assert found[0] == Cause.UPSTREAM_WENT_BACK
    assert "a/1" in found[1]


def test_a_base_that_moved_is_reported_with_the_base_changed_cause(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored("a/1"), stored("a/2", depends_on=("a/1",))])
    store.set_state("a/1", MERGED)

    found = build_base_moved(store)(store.get("a/2"), "spec/a/1", tree=tmp_path, start="")

    assert found is not None
    assert found[0] == Cause.BASE_CHANGED
    assert "spec/a/1" in found[1]


# --- dependents follow a predecessor whose branch is changing ----------------------


def test_each_refresh_follows_predecessors_after_fetching_and_polling(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A poll can send a predecessor back for rework, so the units in review on
    it are tested against what the poll found, not what the pass began with."""
    inst = workspace(tmp_path)
    steps: list[str] = []
    monkeypatch.setattr(cli, "fetch_all", lambda inst: steps.append("fetch"))
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: steps.append("poll"))
    monkeypatch.setattr(
        cli, "follow_predecessors", lambda *args, **kwargs: steps.append("follow") or []
    )
    builder.store.upsert([stored("chain/1"), stored("chain/2", depends_on=("chain/1",))])

    assert tick(inst) == 0

    refreshes = [i for i, step in enumerate(steps) if step == "fetch"]
    assert refreshes
    assert all(steps[i : i + 3] == ["fetch", "poll", "follow"] for i in refreshes)


def app_checkout(inst: Installation, *branches: str) -> dict[str, str]:
    """A real `app` checkout with a commit on each named branch; the branch heads."""
    repo = init_repo(inst.checkouts["app"])
    (repo / "base.txt").write_text("base")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    heads = {}
    for branch in branches:
        git(repo, "checkout", "-q", "-b", branch, "main")
        (repo / "work.txt").write_text(branch)
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", branch)
        heads[branch] = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    return heads


def test_the_branch_head_is_the_local_branch_a_unit_names(tmp_path: Path) -> None:
    inst = workspace(tmp_path)
    heads = app_checkout(inst, "spec/chain/1")

    assert cli.branch_head(inst, stored("chain/1")) == heads["spec/chain/1"]
    assert cli.branch_head(inst, stored("chain/9")) == ""
    assert cli.branch_head(inst, stored("chain/1", repo="elsewhere")) == ""


def test_a_tick_sets_back_a_unit_whose_predecessor_committed_a_rework(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = workspace(tmp_path)
    app_checkout(inst, "spec/chain/1")
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    store = builder.store
    store.upsert([stored("chain/1"), stored("chain/2", depends_on=("chain/1",))])
    store.set_state("chain/1", IN_REVIEW, pr=1, branch="spec/chain/1")
    store.record_push("chain/1", "0" * 40)
    store.set_state("chain/1", RUNNING)
    store.set_state("chain/2", IN_REVIEW, pr=2, branch="spec/chain/2")

    tick(inst)

    # The pass goes on to build what it set back; the entry is what it left.
    assert any(
        entry["state"] == PLANNED and entry.get("cause") == Cause.UPSTREAM_WENT_BACK.value
        for entry in store.get("chain/2").history
    )


# --- a refused start stops only the unit that asked ----------------------------------


def guard_log(monkeypatch: pytest.MonkeyPatch, events: list[str], *, allows) -> None:
    """The guard answers `allows()` and notes in `events` each time it is asked."""

    def decide(reading) -> Decision:
        events.append("guard")
        if allows():
            return Decision(may_start=True, reason="plenty")
        return Decision(may_start=False, reason="session at 99%")

    monkeypatch.setattr(cli, "may_start_unit", decide)


def pauses_for_usage(builder: Builder, monkeypatch: pytest.MonkeyPatch, uid: str) -> None:
    """`uid` ends its first build as a real usage pause leaves a unit: `running`
    with a thread to resume, which the next run that is let through picks up."""
    builder.ends[uid] = (RUNNING, None, "paused before implement")
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: unit_id == uid)


def test_a_unit_refused_for_usage_does_not_stop_the_pass(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal is the unit's: while the guard keeps refusing, the rounds
    still record a merge and a comment; once it allows, the unit waiting for a
    slot is admitted."""
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert(
        [
            stored("stops/1"),
            stored("slow/1", repo="platform"),
            stored("later/1"),
            stored("done/1", repo="platform"),
            stored("talk/1", repo="platform"),
        ]
    )
    builder.store.set_state("done/1", IN_REVIEW, pr=90, branch="spec/done/1")
    builder.store.set_state("talk/1", IN_REVIEW, pr=91, branch="spec/talk/1")
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
    events: list[str] = []
    refused_polls: list[int] = []
    answers: list[bool] = []
    guard_log(
        monkeypatch,
        events,
        allows=lambda: (
            answers.append("stopped" not in events or len(refused_polls) >= 2) or answers[-1]
        ),
    )

    def poll(inst, **kwargs) -> None:
        events.append("poll")
        if "stopped" in events and not answers[-1]:
            refused_polls.append(1)
            if builder.store.get("done/1").state == IN_REVIEW:
                builder.store.set_state("done/1", MERGED, pr=90)
            builder.store.set_feedback("talk/1", "please rename it")

    monkeypatch.setattr(cli, "poll_all", poll)

    def stops() -> str:
        events.append("stopped")
        return "paused"

    pauses_for_usage(builder, monkeypatch, "stops/1")
    builder.scripts["stops/1"] = stops
    builder.scripts["slow/1"] = lambda: (
        None if eventually(lambda: "later/1" in builder.finished) else "failed"
    )

    assert tick(inst) == 0

    assert len(refused_polls) >= 2, "a refused round did not poll"
    assert builder.store.get("done/1").state == MERGED
    assert builder.store.get("talk/1").feedback == "please rename it"
    assert "later/1" in builder.started, "the pass stopped at the refusal"


def test_a_unit_paused_for_usage_resumes_in_the_pass_once_the_guard_allows(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pause leaves the unit `running` with its thread; it is neither
    reclaimed nor started while the guard refuses, and is started again in the
    same tick, ending in review, once the guard allows."""
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("waits/1"), stored("slow/1", repo="platform")])
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
    events: list[str] = []
    answers: list[bool] = []

    def asked_after() -> int:
        return events[events.index("stopped") :].count("guard") if "stopped" in events else 0

    guard_log(
        monkeypatch,
        events,
        allows=lambda: answers.append("stopped" not in events or asked_after() > 3) or answers[-1],
    )
    states_while_refused: list[UnitState] = []

    def poll(inst, **kwargs) -> None:
        if "stopped" in events and not answers[-1]:
            states_while_refused.append(builder.store.get("waits/1").state)

    monkeypatch.setattr(cli, "poll_all", poll)
    runs: list[int] = []

    def pauses_once() -> str | None:
        runs.append(1)
        if len(runs) == 1:
            events.append("stopped")
            return "paused"
        return None

    pauses_for_usage(builder, monkeypatch, "waits/1")
    builder.scripts["waits/1"] = pauses_once
    builder.scripts["slow/1"] = lambda: (
        None if eventually(lambda: builder.finished.count("waits/1") == 2) else "failed"
    )

    assert tick(inst) == 0

    assert states_while_refused and set(states_while_refused) == {RUNNING}
    assert builder.started.count("waits/1") == 2
    assert builder.store.get("waits/1").state == IN_REVIEW


def test_a_window_used_up_leaves_the_paused_unit_and_the_one_behind_it_waiting(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pass goes on, so the guard is asked every round, and says no: the
    paused unit stays `running` and is not started again, and the unit waiting
    behind it is not started."""
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("stops/1"), stored("slow/1", repo="platform"), stored("later/1")])
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
    events: list[str] = []
    guard_log(monkeypatch, events, allows=lambda: "stopped" not in events)

    def stops() -> str:
        events.append("stopped")
        return "paused"

    def asked_after() -> int:
        return events[events.index("stopped") :].count("guard") if "stopped" in events else 0

    pauses_for_usage(builder, monkeypatch, "stops/1")
    builder.scripts["stops/1"] = stops
    builder.scripts["slow/1"] = lambda: None if eventually(lambda: asked_after() >= 3) else "failed"

    assert tick(inst) == 0

    assert asked_after() >= 3, "the guard was not asked again each round"
    assert sorted(builder.started) == ["slow/1", "stops/1"]
    assert builder.store.get("stops/1").state == RUNNING
    assert builder.store.get("later/1").state == PLANNED


def test_a_rate_limit_pause_still_stops_new_builds_for_the_pass(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a usage pause is the unit's. The model's own refusal says nothing
    about the usage endpoint, so it holds every start until its deadline."""
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("mid/1"), stored("slow/1", repo="platform"), stored("later/1")])
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
    marker = tmp_path / "paused.json"
    looks: list[int] = []
    real_is_paused = cli.is_paused

    def counting(state):
        if "mid/1" in builder.finished:
            looks.append(1)
        return real_is_paused(state)

    monkeypatch.setattr(cli, "is_paused", counting)

    def refused_by_the_model() -> None:
        pause.pause_until(
            datetime.now(UTC) + timedelta(hours=1),
            reason="the model refused",
            marker=marker,
            kind="rate_limit",
        )

    builder.scripts["mid/1"] = refused_by_the_model
    # Rounds that went on after the refusal, not a wait of fixed length.
    builder.scripts["slow/1"] = lambda: None if eventually(lambda: len(looks) >= 3) else "failed"

    assert tick(inst) == 0

    assert set(builder.started) == {"mid/1", "slow/1"}
    assert builder.store.get("later/1").state == PLANNED


def test_a_rate_limit_pause_recorded_while_a_round_decides_is_not_cleared_by_it(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard's decision takes time, and a build can record the model's
    refusal in it. The round that then finds room must not resume over it: the
    marker stays and no unit starts after the refusal."""
    inst = workspace(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("mid/1"), stored("slow/1", repo="platform"), stored("later/1")])
    marker = tmp_path / "paused.json"
    refusals: list[int] = []

    def refused_while_deciding(r, **_) -> Decision:
        if not refusals:
            refusals.append(1)
            pause.pause_until(
                datetime.now(UTC) + timedelta(hours=1),
                reason="the model refused",
                marker=marker,
                kind="rate_limit",
            )
        return Decision(may_start=True, reason="plenty")

    monkeypatch.setattr(cli, "may_start_unit", refused_while_deciding)

    assert tick(inst) == 0

    held = pause.is_paused(marker)
    assert held is not None
    assert held.kind == "rate_limit"
    assert builder.started == []
    assert {builder.store.get(unit).state for unit in ("mid/1", "slow/1", "later/1")} == {PLANNED}
