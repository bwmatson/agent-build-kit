"""A round: everything a tick does before it starts builds, run by the tick and
by every refresh of a running pass.

Most cases call `run_round` against a store, with the code host, the model
planner, live verification and archiving faked at their module boundary and
the rest real. The cases about the pass drive `cmd_tick` with a builder whose
completions each test controls, as `test_tick_scheduling` does.
"""

from __future__ import annotations

import argparse
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.archive import is_ready_to_archive
from agent_build_kit.pipeline.pause import is_paused
from agent_build_kit.pipeline.planner import Plan
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.tier2 import stack_lock
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, PLANNED, RUNNING
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.verify import Verification
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.conftest import make_installation
from tests.factories import stored_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

WAIT = 5

TASKS = """# Tasks

Acceptance: none — a fixture about rounds, not about the acceptance group

## 1. [app] [tier1] Register the marker

- [ ] 1.1 Test: it selects only marked tests.
- [ ] 1.2 Register it.
"""


def eventually(condition: Callable[[], bool]) -> bool:
    deadline = time.monotonic() + WAIT
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        limits={
            "max_concurrent_stacks": 4,
            "stack_depth_build_cap": 3,
            "max_units_in_progress": 50,
        },
    )


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """The network, the thread database and the usage window stubbed;
    planning, verification, archive, reclaim and evaluation are the real ones
    unless a test fakes them."""
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "convert_in_flight", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: False)
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    monkeypatch.setattr(cli, "may_start_unit", lambda r: Decision(may_start=True, reason="plenty"))


def unit_of(uid: str, **overrides) -> StoredUnit:
    change, _, _ = uid.partition("/")
    return stored_unit(uid, change=change, **overrides)


def write_change(root: Path, name: str, tasks: str = TASKS) -> Path:
    path = root / "openspec" / "changes" / name
    path.mkdir(parents=True, exist_ok=True)
    (path / "tasks.md").write_text(tasks)
    return path / "tasks.md"


def planning(monkeypatch: pytest.MonkeyPatch, calls: list[dict] | None = None) -> None:
    """A planner that answers every change with one unit, `<change>/1`."""

    def plan(**kwargs) -> Plan:
        if calls is not None:
            calls.append(kwargs)
        (change,) = kwargs["changes"]
        return Plan(units=(unit_of(f"{change}/1"),))

    monkeypatch.setattr(cli, "plan_round", plan)


def run(
    inst: Installation,
    store: UnitStore,
    *,
    building: set[str] | None = None,
    started: set[str] | None = None,
    only: frozenset[str] = frozenset(),
    submit: bool = True,
) -> list[str]:
    """The ids of the units a round returns to start."""
    ready = cli.run_round(
        inst,
        store,
        building=set() if building is None else building,
        started=set() if started is None else started,
        only=only,
        submit=submit,
    )
    return [unit.id for unit in ready]


# --- 1.1 a change written while a unit builds ----------------------------------------------


def test_a_change_added_between_refreshes_is_planned_stored_paged_and_started(
    inst: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = cli.store_for(inst)
    store.upsert([unit_of("slow/1", repo="platform")])
    store.set_state("slow/1", RUNNING, branch="spec/slow/1")
    planning(monkeypatch)
    write_change(tmp_path, "add-marker")

    ready = run(inst, store, building={"slow/1"}, started={"slow/1"})

    assert ready == ["add-marker/1"]
    assert store.get("add-marker/1").state == PLANNED
    assert UnitStore(tmp_path / "units.json").get("add-marker/1").id == "add-marker/1"
    assert "add-marker/1" in inst.graph_page.read_text()
    assert store.get("slow/1").state == RUNNING


def test_a_round_returns_nothing_to_start_when_not_asked_to_submit(
    inst: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = UnitStore(tmp_path / "units.json")
    planning(monkeypatch)
    write_change(tmp_path, "add-marker")

    assert run(inst, store, submit=False) == []
    assert store.get("add-marker/1").state == PLANNED


# --- 1.2 nothing new; a failing step --------------------------------------------------------


def test_a_round_with_every_change_unchanged_plans_nothing_and_changes_no_unit(
    inst: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = UnitStore(tmp_path / "units.json")
    calls: list[dict] = []
    planning(monkeypatch, calls)
    write_change(tmp_path, "add-marker")
    run(inst, store, submit=False)
    store.set_state("add-marker/1", IN_REVIEW, pr=7, branch="spec/add-marker/1")
    before = store.all()

    run(inst, store, submit=False)

    assert len(calls) == 1, "an unchanged change was planned again"
    assert store.all() == before


def test_a_planner_that_raises_is_logged_and_the_change_is_tried_at_the_next_round(
    inst: Installation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit_of("feature/1"), unit_of("stranded/1")])
    store.set_state("stranded/1", RUNNING, branch="spec/stranded/1")
    write_change(tmp_path, "add-marker")

    def explode(**kwargs):
        raise RuntimeError("no JSON in the planner's output")

    monkeypatch.setattr(cli, "plan_round", explode)

    ready = run(inst, store)

    out = capsys.readouterr().out
    assert "RuntimeError" in out
    assert "add-marker" in out
    assert "stranded/1" in ready, "the steps after planning did not run"
    assert "feature/1" in ready

    planning(monkeypatch)
    run(inst, store)
    assert store.get("add-marker/1").id == "add-marker/1"


@pytest.mark.parametrize(
    "step",
    [
        "convert_in_flight",
        "plan_all",
        "link_needs",
        "verify_ready",
        "archive_ready_changes",
        "reclaim_stranded",
    ],
)
def test_a_step_that_raises_is_logged_and_the_round_still_starts_what_is_ready(
    inst: Installation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    step: str,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit_of("feature/1")])

    def explode(*args, **kwargs):
        raise ValueError("step failed")

    monkeypatch.setattr(cli, step, explode)

    assert run(inst, store) == ["feature/1"]

    out = capsys.readouterr().out
    assert "ValueError" in out
    assert "step failed" in out


# --- 1.3 verify and archive while another unit builds -------------------------------------


@pytest.fixture
def verified(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Live verification at its lowest boundary, `verify_change`, which the
    stack lock wraps; the changes it was asked about."""
    asked: list[str] = []

    def verify(change, units, **kwargs) -> Verification:
        asked.append(change)
        merged = sorted(u.id for u in units if u.carries(change) and u.state == MERGED and u.pr)
        return Verification(change=change, passed=True, units=merged)

    monkeypatch.setattr(cli, "verify_change", verify)
    return asked


@pytest.fixture
def archived(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    done: list[str] = []

    def archive(units, *, may_archive, **kwargs) -> list[str]:
        changes = sorted({u.change for u in units})
        ready = [c for c in changes if is_ready_to_archive(c, units) and may_archive(c)]
        done.extend(ready)
        return ready

    monkeypatch.setattr(cli, "archive_ready_changes", archive)
    return done


def merged_beside_a_build(store: UnitStore) -> None:
    store.upsert([unit_of("done/1"), unit_of("slow/1", repo="platform")])
    store.set_state("done/1", MERGED, pr=3, branch="spec/done/1")
    store.set_state("slow/1", RUNNING, branch="spec/slow/1")


def in_a_thread(work: Callable[[], object]) -> None:
    """Runs `work` and fails, rather than hangs, if it waits on a lock."""
    raised: list[BaseException] = []

    def guarded() -> None:
        try:
            work()
        except BaseException as error:  # noqa: BLE001 — re-raised below, in the test
            raised.append(error)

    thread = threading.Thread(target=guarded, daemon=True)
    thread.start()
    thread.join(WAIT)
    assert not thread.is_alive(), "the round waited for the live-stack lock"
    if raised:
        raise raised[0]


def test_a_change_whose_units_have_merged_is_verified_and_archived_while_another_builds(
    inst: Installation, tmp_path: Path, verified: list[str], archived: list[str]
) -> None:
    store = UnitStore(tmp_path / "units.json")
    merged_beside_a_build(store)

    run(inst, store, building={"slow/1"}, started={"slow/1"})

    assert verified == ["done"]
    assert archived == ["done"]
    assert store.get("slow/1").state == RUNNING


def test_verification_is_skipped_and_logged_while_the_live_stack_is_in_use_then_done_later(
    inst: Installation,
    tmp_path: Path,
    verified: list[str],
    archived: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = UnitStore(tmp_path / "units.json")
    merged_beside_a_build(store)

    with stack_lock(inst.state_dir / "tier2.lock"):
        in_a_thread(lambda: run(inst, store, building={"slow/1"}, started={"slow/1"}))

        assert verified == []
        assert archived == []
        out = capsys.readouterr().out
        assert "done" in out
        assert "skipped" in out

    run(inst, store, building={"slow/1"}, started={"slow/1"})

    assert verified == ["done"]
    assert archived == ["done"]


def test_a_round_does_not_verify_when_no_change_has_merged(
    inst: Installation, tmp_path: Path, verified: list[str]
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit_of("slow/1", repo="platform")])
    store.set_state("slow/1", RUNNING, branch="spec/slow/1")

    with stack_lock(inst.state_dir / "tier2.lock"):
        in_a_thread(lambda: run(inst, store, building={"slow/1"}))

    assert verified == []


# --- 1.4 reclaim spares what the pass holds ----------------------------------------------


def running(store: UnitStore, *ids: str) -> None:
    store.upsert([unit_of(uid) for uid in ids])
    for uid in ids:
        store.set_state(uid, RUNNING, branch=f"spec/{uid}")


def test_a_unit_marked_running_with_no_run_and_no_thread_is_reclaimed_and_may_start(
    inst: Installation, tmp_path: Path
) -> None:
    store = UnitStore(tmp_path / "units.json")
    running(store, "killed/1")

    ready = run(inst, store)

    assert store.get("killed/1").state in (PLANNED, RUNNING)
    assert ready == ["killed/1"]
    assert "requeued" in str(store.get("killed/1").history[-1].get("note", ""))


def test_a_unit_a_live_process_holds_is_not_reclaimed_by_a_round(
    inst: Installation, tmp_path: Path
) -> None:
    store = UnitStore(tmp_path / "units.json")
    running(store, "held/1")

    with branch_lock("spec/held/1", root=inst.state_dir / "locks"):
        run(inst, store)

    assert store.get("held/1").state == RUNNING


def test_a_unit_in_the_passes_building_set_is_not_reclaimed(
    inst: Installation, tmp_path: Path
) -> None:
    store = UnitStore(tmp_path / "units.json")
    running(store, "building/1")

    run(inst, store, building={"building/1"}, started={"building/1"})

    assert store.get("building/1").state == RUNNING


def test_a_unit_just_submitted_whose_worker_has_not_taken_its_lock_is_not_reclaimed(
    inst: Installation, tmp_path: Path
) -> None:
    """In the pool but not in `building`, as a unit is between the submit and
    the worker's lock; the pass's started set is what says so."""
    store = UnitStore(tmp_path / "units.json")
    running(store, "handed/1")

    run(inst, store, building=set(), started={"handed/1"})

    assert store.get("handed/1").state == RUNNING


# --- 1.5 the guard ------------------------------------------------------------------------


def refusing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli, "may_start_unit", lambda r: Decision(may_start=False, reason="session at 88%")
    )


def test_a_round_whose_guard_refuses_records_the_pause_once_and_starts_nothing(
    inst: Installation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit_of("feature/1")])
    refusing(monkeypatch)

    assert run(inst, store) == []
    assert run(inst, store) == []

    assert is_paused(tmp_path / "paused.json") is not None
    out = capsys.readouterr().out
    assert out.count("pausing until") == 1
    assert "session at 88%" in out
    assert store.get("feature/1").state == PLANNED


def test_the_round_after_the_guard_allows_starts_work_again(
    inst: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit_of("feature/1")])
    refusing(monkeypatch)
    assert run(inst, store) == []

    monkeypatch.setattr(cli, "may_start_unit", lambda r: Decision(may_start=True, reason="room"))

    assert run(inst, store) == ["feature/1"]
    assert is_paused(tmp_path / "paused.json") is None


class Builder:
    """Stands in for `build_runner`: a unit's build runs its script, if it has
    one, and opens a pull request."""

    def __init__(self, store: UnitStore) -> None:
        self.store = store
        self.scripts: dict[str, Callable[[], str | None]] = {}
        self.started: list[str] = []
        self.finished: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, unit, **kwargs) -> Builder:
        return self

    def run(self, unit, *, base, graph) -> RunOutcome:
        with self._lock:
            self.started.append(unit.id)
            pr = len(self.started)
        self.store.set_state(unit.id, RUNNING, branch=f"spec/{unit.id}")
        status = self.scripts.get(unit.id, lambda: None)() or "open"
        if status == "open":
            self.store.set_state(unit.id, IN_REVIEW, pr=pr)
        else:
            self.store.set_state(unit.id, PLANNED, note=f"{status} before implement")
        with self._lock:
            self.finished.append(unit.id)
        return RunOutcome(status=RunStatus(status), detail=unit.id, pr=pr)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    fake = Builder(UnitStore(tmp_path / "units.json"))
    monkeypatch.setattr(cli, "build_runner", fake)
    return fake


def tick(inst: Installation, *, dry_run: bool = False, only: list[str] | None = None) -> int:
    args = argparse.Namespace(dry_run=dry_run)
    if only is not None:
        args.only = only
    return cli.cmd_tick(args, inst)


def test_a_guard_that_refuses_mid_pass_starts_nothing_and_lets_the_builds_in_flight_finish(
    inst: Installation, tmp_path: Path, builder: Builder, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder.store.upsert([unit_of("slow/1", repo="platform")])
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
    answers: list[int] = []

    def guard(reading) -> Decision:
        answers.append(1)
        if len(answers) == 1:
            return Decision(may_start=True, reason="plenty")
        return Decision(may_start=False, reason="session at 88%")

    def poll(inst, **kwargs) -> None:
        # Something new turns up while slow/1 builds.
        if "late/1" not in {u.id for u in builder.store.all()}:
            builder.store.upsert([unit_of("late/1")])

    monkeypatch.setattr(cli, "may_start_unit", guard)
    monkeypatch.setattr(cli, "poll_all", poll)
    builder.scripts["slow/1"] = lambda: (
        None if eventually(lambda: is_paused(tmp_path / "paused.json") is not None) else "failed"
    )

    assert tick(inst) == 0

    assert builder.started == ["slow/1"]
    assert builder.store.get("slow/1").state == IN_REVIEW
    assert builder.store.get("late/1").state == PLANNED


# --- 1.6 editing a building change's tasks ---------------------------------------------


def test_editing_the_tasks_of_a_change_whose_unit_builds_replans_it_and_leaves_the_unit_alone(
    inst: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = UnitStore(tmp_path / "units.json")
    calls: list[dict] = []
    planning(monkeypatch, calls)
    path = write_change(tmp_path, "add-marker")
    run(inst, store, submit=False)
    store.set_state("add-marker/1", RUNNING, branch="spec/add-marker/1", pr=7)
    unit = store.get("add-marker/1")
    building, started = {"add-marker/1"}, {"add-marker/1"}

    path.write_text(TASKS + "\n## 2. [app] [tier1] More\n\n- [ ] 2.1 Do it.\n")
    ready = run(inst, store, building=building, started=started)

    assert len(calls) == 2, "the edit was not planned"
    after = store.get("add-marker/1")
    assert (after.state, after.branch, after.pr) == (RUNNING, unit.branch, unit.pr)
    assert after.history == unit.history
    assert "add-marker/1" not in ready
    assert building == {"add-marker/1"}
    assert started == {"add-marker/1"}


# --- 1.7 the tick and the loop call the same function ---------------------------------


@pytest.fixture
def rounds(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Each call to `run_round`, with the sets it was given copied as they were."""
    calls: list[dict] = []
    original = cli.run_round

    def spy(inst, store, **kwargs):
        calls.append(
            {
                "building": set(kwargs["building"]),
                "started": set(kwargs["started"]),
                "only": kwargs["only"],
            }
        )
        return original(inst, store, **kwargs)

    monkeypatch.setattr(cli, "run_round", spy)
    return calls


def test_the_tick_and_every_refresh_of_the_pass_run_the_same_round(
    inst: Installation,
    builder: Builder,
    rounds: list[dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder.store.upsert([unit_of("slow/1", repo="platform")])
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
    builder.scripts["slow/1"] = lambda: (
        None if eventually(lambda: sum(1 for r in rounds if r["building"]) >= 2) else "failed"
    )

    assert tick(inst) == 0

    assert builder.store.get("slow/1").state == IN_REVIEW
    assert rounds[0]["building"] == set(), "the tick's own round came first"
    assert sum(1 for r in rounds if r["building"] == {"slow/1"}) >= 2


def test_a_dry_run_runs_a_round_and_builds_nothing(
    inst: Installation, builder: Builder, rounds: list[dict], capsys: pytest.CaptureFixture[str]
) -> None:
    builder.store.upsert([unit_of("feature/1")])

    assert tick(inst, dry_run=True) == 0

    assert len(rounds) == 1
    assert builder.started == []
    out = capsys.readouterr().out
    assert "ready: feature/1" in out
    assert "dry run" in out


def test_only_narrows_every_round(inst: Installation, builder: Builder, rounds: list[dict]) -> None:
    builder.store.upsert([unit_of("feature/1"), unit_of("other/1")])

    assert tick(inst, only=["other/1"]) == 0

    assert builder.started == ["other/1"]
    assert rounds
    assert all(r["only"] == frozenset({"other/1"}) for r in rounds)


def test_a_unit_a_poll_sends_back_is_readmitted_by_the_round_and_rebuilt(
    inst: Installation,
    builder: Builder,
    rounds: list[dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder.store.upsert([unit_of("conflicted/1"), unit_of("slow/1", repo="platform")])
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
    sent: list[int] = []

    def poll(inst, **kwargs) -> None:
        if builder.store.get("conflicted/1").state == IN_REVIEW and not sent:
            sent.append(1)
            builder.store.set_state(
                "conflicted/1", PLANNED, note="rework requested: merge conflict with its base"
            )

    monkeypatch.setattr(cli, "poll_all", poll)
    builder.scripts["slow/1"] = lambda: (
        None if eventually(lambda: builder.finished.count("conflicted/1") == 2) else "failed"
    )

    assert tick(inst) == 0

    assert builder.started.count("conflicted/1") == 2
    assert any(r["building"] for r in rounds), "the loop ran no round"
