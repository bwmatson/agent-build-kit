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
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import pause
from agent_build_kit.pipeline.stack_runner import RunOutcome, UnitRunner
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import (
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    local_ref,
    ready_units,
)
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.wiring import build_base_moved, build_upstream_incomplete
from tests.conftest import make_installation

# How long a build waits for something the pass should make happen meanwhile.
# Long enough never to trip when the pass does it; against a pass that fixes
# its batch at the start, it is what the slow unit waits before giving up.
WAIT = 5


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
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Everything around building stubbed: GitHub, the network, planning,
    live verification and the usage window. Tests about those replace the
    stub they need."""
    monkeypatch.setattr(pause, "systemd_resume", lambda seconds, command, **k: None)
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "_has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "verify_ready", lambda inst, units, **kwargs: lambda change: True)
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: [])
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    monkeypatch.setattr(cli, "may_start_unit", lambda r: Decision(may_start=True, reason="plenty"))


def workspace(tmp_path: Path, *, max_concurrent: int = 4, depth_cap: int = 3) -> Installation:
    return make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        limits={"max_concurrent_stacks": max_concurrent, "stack_depth_cap": depth_cap},
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
        else:
            self.store.set_state(unit.id, PLANNED, note=f"{status} before implement")
        with self._lock:
            self.finished.append(unit.id)
        return RunOutcome(status=status, detail=f"{status} {unit.id}", pr=pr)


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


def test_a_unit_set_back_to_planned_during_the_pass_is_started_by_it(
    builder: Builder, tmp_path: Path
) -> None:
    """Setting a unit back to `planned` is the documented recovery once the
    cause of its failure is fixed; with slots free, the pass in flight picks
    it up rather than leaving it for the next one."""
    inst = workspace(tmp_path)
    builder.store.upsert([stored("feature/1"), stored("feature/2")])
    builder.store.set_state("feature/2", "failed")

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


def test_a_build_that_says_stop_ends_scheduling(builder: Builder, tmp_path: Path) -> None:
    """One slot: the first unit opens its PR and the second starts in the same
    pass; the second finds the usage window spent, and the third is not
    started — its report is acted on, not discarded."""
    inst = workspace(tmp_path, max_concurrent=1)
    builder.store.upsert([stored("feature/1"), stored("feature/2"), stored("feature/3")])
    builder.scripts["feature/2"] = lambda: "paused"

    assert tick(inst) == 0

    assert builder.started == ["feature/1", "feature/2"]
    assert builder.store.get("feature/3").state == PLANNED
    assert (tmp_path / "paused.json").exists()


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
    builder.scripts["stops/1"] = lambda: "paused"
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


def test_a_failing_refresh_is_logged_and_the_pass_continues(
    builder: Builder,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = workspace(tmp_path, max_concurrent=1)
    builder.store.upsert([stored("feature/1"), stored("feature/2")])
    polls: list[int] = []

    def poll(inst, **kwargs):
        polls.append(1)
        if len(polls) > 1:
            raise RuntimeError("github unreachable")

    monkeypatch.setattr(cli, "poll_all", poll)

    assert tick(inst) == 0

    assert builder.started == ["feature/1", "feature/2"]
    assert len(polls) >= 2
    assert "github unreachable" in capsys.readouterr().out


def test_planning_happens_once_per_pass(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Planning is an agent call, and nothing in a pass creates a unit for it
    to find."""
    inst = workspace(tmp_path, max_concurrent=1)
    builder.store.upsert([stored("feature/1"), stored("feature/2"), stored("feature/3")])
    plans: list[int] = []
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: plans.append(1))

    assert tick(inst) == 0

    assert builder.started == ["feature/1", "feature/2", "feature/3"]
    assert plans == [1]


# --- a refresh mid-pass leaves the builds in flight alone --------------------------

# Captured before the autouse fixture stubs it: this test needs the real
# dispatch wiring, with only GitHub and git faked beneath it.
REAL_POLL_ALL = cli.poll_all


@pytest.mark.parametrize("step", ["test tasks", "remaining tasks"], ids=["tests", "implement"])
def test_a_parent_merging_while_its_child_builds_moves_the_child_before_its_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    """The refresh after another unit's completion hears that the parent
    merged while its same-repo child is still building. It records the merge
    but leaves the child's branch alone — restacking would rebase the tree the
    agent is writing to. The child's build sees its base moved and stops
    before pushing; the next pass restacks it onto the trunk and opens its PR
    there, not against the merged branch.

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

    def runner(unit, *, store: UnitStore, installation, log) -> UnitRunner:
        def claude(prompt: str, *, cwd: Path) -> str:
            if unit.id == "chain/2" and step in prompt:
                # Still at this step when the merge is heard.
                assert merged.wait(WAIT), "the refresh never reported the merge"
            return ""

        def commit(message: str, *, cwd: Path) -> int:
            commits[unit.id] = commits.get(unit.id, 0) + 1
            return 1

        def open_pr(u, *, body: str, base: str, cwd: Path) -> int:
            opened.append((u.id, base))
            return 20 + len(opened)

        return UnitRunner(
            store=store,
            planning_repo=tmp_path / "planning",
            worktree=lambda u, base: tmp_path / "trees" / u.id,
            may_start=lambda: (True, ""),
            run_claude=claude,
            run_rework=claude,
            run_review=lambda *, cwd, context="": '{"approved": true}',
            run_rework_review=lambda *, cwd, context="": '{"approved": true}',
            commit=commit,
            branch_commits=lambda tree, ref: branch_commits(unit.id, ref),
            head=lambda tree: f"{unit.id}@{commits.get(unit.id, 0)}",
            upstream_incomplete=build_upstream_incomplete(store),
            base_moved=build_base_moved(store),
            restack_onto=lambda *, tree, branch, base, unit: moved_onto.append((unit.id, base)),
            run_tier1=lambda *, cwd, base: (True, ""),
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
    child = store.get("chain/2")
    assert child.state == PLANNED, child.history
    assert child.resume_from, "held at a checkpoint, not failed"

    assert tick(inst) == 0

    assert moved_onto == [("chain/2", local_ref("main"))]
    assert ("chain/2", "main") in opened
    assert store.get("chain/2").state == IN_REVIEW
