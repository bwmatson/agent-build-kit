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
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import pause
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import (
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SETTLING,
    UnitState,
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
from tests.tick_pass import (
    Builder,
    install_builder,
    isolate,
    stored,
    tick,
    tick_until_idle,
    warm_unit_graphs,
    workspace,
)

# How long a build waits for something the pass should make happen meanwhile.
# Long enough never to trip when the pass does it; against a pass that fixes
# its batch at the start, it is what the slow unit waits before giving up.
WAIT = 30

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def warmed(tmp_path: Path) -> None:
    warm_unit_graphs(tmp_path)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


# --- 1.1 what a completion releases starts in the same pass -----------------------


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


# --- 1.2 the slots stay full, and the caps still hold ------------------------------


# --- 1.3 stopping, and --only ------------------------------------------------------


# --- 1.4 refreshing from the code host, and planning once --------------------------


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

    def moves_with_a_turn(*args, turn, **kwargs) -> None:
        """The move holds the turn only for its git phases, so it is handed the
        turn to take, which is the repo's lock."""
        with turn():
            records_the_turn()

    monkeypatch.setattr(cli, "resolved_move", moves_with_a_turn)
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

    assert store.get("add-marker/1").state == SETTLING
    assert store.get("feature/1").state == IN_REVIEW


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
        project_limits=dict(max_units_in_progress=limit),
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
    assert "app: 2 units in progress, limit 2 (2 in review)" in out
    assert "platform" not in out


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

    # Its only change is the readiness stamp a pause still dates.
    unstamped = [unit.model_copy(update={"ready_at": None}) for unit in builder.store.all()]
    assert unstamped == before
    assert "session at 88%" in capsys.readouterr().out


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


def test_a_refresh_fetches_and_polls_and_the_round_follows_predecessors_beside_the_gates(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A poll can send a predecessor back for rework, so the units in review on
    it are tested against what the poll found, not what the pass began with. The
    pass is a step of the round, after the refresh and beside the steps that
    gate and release units, not a part of the refresh."""
    inst = workspace(tmp_path)
    steps: list[str] = []

    def record(name: str) -> Callable[..., list[str]]:
        return lambda *args, **kwargs: steps.append(name) or []

    for attribute, name in (
        ("fetch_all", "fetch"),
        ("poll_all", "poll"),
        ("deliver_committed", "commits"),
        ("reclaim_stranded", "reclaim"),
        ("follow_predecessors", "follow"),
        ("gate_sent_back", "gate"),
        ("release_gated", "release"),
    ):
        monkeypatch.setattr(cli, attribute, record(name))
    builder.store.upsert([stored("chain/1"), stored("chain/2", depends_on=("chain/1",))])

    cli.run_round(
        inst, builder.store, building=set(), started=set(), only=frozenset(), submit=False
    )

    assert steps[:2] == ["fetch", "poll"], "the refresh is the fetch and the poll"
    assert steps.count("follow") == 1
    assert steps.index("follow") > steps.index("reclaim")
    assert set(steps[-3:]) == {"follow", "gate", "release"}
    assert steps.index("gate") < steps.index("release")


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


def test_no_more_than_the_concurrency_cap_build_at_once(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each tick hands out no more than the cap: measured where units are handed out, over
    ticks that run until nothing is left to start. The workers run to their ends inside a tick,
    so nothing is in flight when the next evaluates. The cap applies to each project, so one
    repo."""
    inst = workspace(tmp_path, max_concurrent=2)
    ids = [f"many/{n}" for n in range(1, 7)]
    builder.store.upsert([stored(uid, repo="app") for uid in ids])

    at_each_evaluation: list[int] = []

    def evaluate(graph, **kwargs):
        ready = ready_units(graph, **kwargs)
        if kwargs["max_concurrent"] > inst.max_concurrent_stacks:
            return ready  # the look at who is only waiting for a slot hands nothing out
        at_each_evaluation.append(len(ready))
        return ready

    monkeypatch.setattr(cli, "ready_units", evaluate)

    assert tick_until_idle(inst) == 0

    assert sorted(builder.started) == sorted(ids)
    assert len(at_each_evaluation) > 2
    assert max(at_each_evaluation) <= 2, at_each_evaluation


def test_a_chain_past_the_depth_cap_is_still_held_back(builder: Builder, tmp_path: Path) -> None:
    """Ticking again builds a chain link by link — until it has run as far ahead of review as
    the depth cap allows, where it stops."""
    inst = workspace(tmp_path, depth_cap=2)
    builder.store.upsert(
        [
            stored("chain/1"),
            stored("chain/2", depends_on=("chain/1",)),
            stored("chain/3", depends_on=("chain/2",)),
        ]
    )

    assert tick_until_idle(inst) == 0

    assert builder.started == ["chain/1", "chain/2"]
    assert builder.store.get("chain/3").state == PLANNED


def test_only_narrows_every_evaluation(builder: Builder, tmp_path: Path) -> None:
    """Narrowed to two links of a chain, the ticks build both — the second once the first
    unblocks it — and not the third, which the second's completion unblocks in turn."""
    inst = workspace(tmp_path)
    builder.store.upsert(
        [
            stored("chain/1"),
            stored("chain/2", depends_on=("chain/1",)),
            stored("chain/3", depends_on=("chain/2",)),
        ]
    )

    assert tick_until_idle(inst, only=["chain/1", "chain/2"]) == 0

    assert builder.started == ["chain/1", "chain/2"]
    assert builder.store.get("chain/3").state == PLANNED


def test_one_short_of_the_limit_starts_one_new_unit_not_all(
    builder: Builder, tmp_path: Path
) -> None:
    inst = limit_workspace(tmp_path, 2)
    open_pr(builder, "one/1", 11)
    builder.store.upsert([stored("new/1"), stored("new/2")])

    assert tick(inst) == 0

    assert builder.started == ["new/1"]


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
