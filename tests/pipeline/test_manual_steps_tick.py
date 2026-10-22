"""The tick runs the checks of the manual steps and readmits the unit (spec: manual-steps).

The checks are real scripts in a stand-in worktree, so each test reaches the check through the
process boundary the tick does: its exit status, its first lines of output and its signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import main
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.manual_steps import evaluate_manual_steps
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import FAILED, HELD, PLANNED, ManualStep
from agent_build_kit.pipeline.vocabulary import WaitReason
from agent_build_kit.pipeline.wait_log import Wait
from agent_build_kit.pipeline.workspaces import worktree_path
from tests.conftest import make_installation, run_status
from tests.factories import stored_unit, unit
from tests.graph.test_session_continuation import Sessions, agents
from tests.graph_driver import fresh, tick
from tests.parked_split_support import stub_round
from tests.redaction_fakes import SECRET, known

NOW = datetime(2026, 10, 11, tzinfo=UTC)
UNIT = "feature/1"
BRANCH = "spec/feature/1"
SLUG = "flip-marker"
RUNBOOK = "docs/runbook-x.md#flip"
SCRIPT = f".abk/manual/{SLUG}.sh"
MISSING = "config missing"


@dataclass
class World:
    inst: Installation
    store: UnitStore
    tree: Path

    def script(self, body: str, name: str = f"{SLUG}.sh") -> str:
        path = self.tree / ".abk" / "manual" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)
        return f".abk/manual/{name}"

    def wait_on(self, *steps: ManualStep, uid: str = UNIT) -> None:
        """`uid` as a run leaves it after raising `steps`: planned, with its branch and the step
        it stopped at."""
        self.store.set_manual_steps(uid, steps)
        self.store.record_step(uid, "open_pr")
        self.store.set_state(
            uid, PLANNED, branch=f"spec/{uid}", note="raised a step", cause=Cause.MANUAL_STEP
        )

    def step(self, slug: str = SLUG) -> ManualStep:
        return next(s for s in self.store.get(UNIT).manual_steps if s.slug == slug)

    def evaluate(self) -> None:
        evaluate_manual_steps(self.inst, now=NOW)

    def waits(self, **kw: Any) -> dict[str, Wait]:
        return cli.wait_reasons(
            self.inst,
            self.store.all(),
            started=set(),
            building=set(),
            only=frozenset(),
            usage_paused=False,
            **kw,
        )


def make_world(tmp_path: Path, *, slots: int = 50, seconds: int = 2) -> World:
    inst = make_installation(
        tmp_path / "planning",
        planning=dict(state_dir=".", worktree_root=str(tmp_path / "trees")),
        limits=dict(manual_check_seconds=seconds),
        project_limits=dict(max_units_in_progress=slots),
    )
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([stored_unit(UNIT, change="feature")])
    tree = worktree_path(inst.checkouts["app"], BRANCH, inst.worktree_root)
    tree.mkdir(parents=True)
    return World(inst, store, tree)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return make_world(tmp_path)


def raised(check: str, slug: str = SLUG) -> ManualStep:
    return ManualStep(slug=slug, text="A person flips the marker", runbook=RUNBOOK, check=check)


def passing_once_flagged(world: World) -> str:
    """A check that passes while `flag` exists in the worktree and says what is missing else."""
    return world.script(f'test -f flag && exit 0\necho "{MISSING}"\nexit 1')


# --- the result of a check -------------------------------------------------------------------


def test_a_failing_check_leaves_the_step_unmet_and_keeps_the_line_it_printed(world: World) -> None:
    world.wait_on(raised(passing_once_flagged(world)))

    world.evaluate()

    step = world.step()
    assert (step.done, step.outcome, step.last_line) == (False, "unmet", MISSING)
    assert step.checked_at == NOW


def test_a_passing_check_marks_the_step_done_and_readmits_the_unit_where_it_stopped(
    world: World,
) -> None:
    world.wait_on(raised(passing_once_flagged(world)))
    (world.tree / "flag").write_text("")
    before = len(world.store.history(UNIT))

    world.evaluate()

    stored = world.store.get(UNIT)
    assert world.step().done is True
    assert stored.state == PLANNED and stored.step == "open_pr"
    assert world.waits()[UNIT].reason is not WaitReason.MANUAL
    added = world.store.history(UNIT)[before:]
    assert len(added) == 1 and SLUG in added[0]["note"]


def test_a_step_that_is_done_stays_done_when_the_check_later_fails(world: World) -> None:
    world.wait_on(raised(passing_once_flagged(world)))
    (world.tree / "flag").write_text("")
    world.evaluate()
    (world.tree / "flag").unlink()
    entries = len(world.store.history(UNIT))

    world.evaluate()

    assert world.step().done is True
    assert len(world.store.history(UNIT)) == entries


def test_an_unchanged_result_adds_no_history_and_a_changed_one_adds_one(world: World) -> None:
    check = world.script(f'echo "{MISSING}: $(cat state)"; exit 1')
    (world.tree / "state").write_text("a")
    world.wait_on(raised(check))
    world.evaluate()
    entries = len(world.store.history(UNIT))

    world.evaluate()
    unchanged = len(world.store.history(UNIT))
    (world.tree / "state").write_text("b")
    world.evaluate()

    assert unchanged == entries
    assert len(world.store.history(UNIT)) == entries + 1


def test_a_unit_with_two_steps_is_readmitted_only_when_both_are_done(world: World) -> None:
    first = raised(world.script("exit 0", "first.sh"), "first")
    second = raised(passing_once_flagged(world), "second")
    world.wait_on(first, second)

    world.evaluate()

    assert (world.step("first").done, world.step("second").done) == (True, False)
    assert world.waits()[UNIT].reason is WaitReason.MANUAL
    (world.tree / "flag").write_text("")
    world.evaluate()
    assert world.waits()[UNIT].reason is not WaitReason.MANUAL


@pytest.mark.parametrize(
    "body",
    ["exit 3", "kill -9 $$", "exec sleep 30", None],
    ids=["no output", "signal", "timeout", "no script"],
)
def test_a_check_that_fails_to_answer_leaves_the_step_unmet_and_the_status_says_so(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    body: str | None,
) -> None:
    world = make_world(tmp_path, seconds=1)
    check = SCRIPT if body is None else world.script(body)
    world.wait_on(raised(check))

    world.evaluate()

    assert world.step().done is False
    assert world.step().outcome in ("failed", "timeout")
    lines = run_status(world.inst, monkeypatch, capsys)
    waiting = next(line for line in lines if "waiting for manual step" in line)
    assert "check failed" in waiting and "passed" not in waiting


def test_the_output_is_bounded_and_redacted(world: World) -> None:
    long = "x" * 20000
    world.wait_on(raised(world.script(f'echo "{long} {SECRET}"; exit 1')))

    with known():
        world.evaluate()

    line = world.step().last_line
    assert SECRET not in line
    assert 0 < len(line) < 1000


def test_the_check_runs_in_the_worktree_with_a_minimal_environment(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOME_TOKEN", "not-for-the-check")
    world.wait_on(raised(world.script('echo "$(pwd -P) ${SOME_TOKEN:-unset}"; exit 1')))

    world.evaluate()

    assert world.step().last_line == f"{world.tree.resolve()} unset"


def test_a_declared_check_command_runs_through_the_shell_in_the_worktree(world: World) -> None:
    declared = ManualStep(slug=SLUG, text="A person", runbook=RUNBOOK, check="test -f marker.txt")
    world.wait_on(declared)

    world.evaluate()
    assert world.step().done is False
    (world.tree / "marker.txt").write_text("")
    world.evaluate()

    assert world.step().done is True


def test_the_script_is_removed_when_its_step_completes_and_the_removal_is_logged(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    check = passing_once_flagged(world)
    world.wait_on(raised(check))
    world.evaluate()
    assert (world.tree / check).is_file(), "kept while the step is unmet"
    (world.tree / "flag").write_text("")
    capsys.readouterr()

    world.evaluate()

    out = capsys.readouterr()
    assert not (world.tree / check).exists()
    assert "removed" in (out.out + out.err) and f"{SLUG}.sh" in (out.out + out.err)


# --- the pass --------------------------------------------------------------------------------


def test_a_round_runs_each_check_once_and_readmits_the_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scripted_engine: None
) -> None:
    stub_round(monkeypatch)
    world = make_world(tmp_path)
    check = world.script('echo run >> runs\ntest -f flag && exit 0\necho "config missing"\nexit 1')
    world.wait_on(raised(check))
    runs = world.tree / "runs"

    cli.run_round(world.inst, world.store, building=(), only=frozenset(), submit=False)
    cli.run_round(world.inst, world.store, building=(), only=frozenset(), submit=False)
    (world.tree / "flag").write_text("")
    cli.run_round(world.inst, world.store, building=(), only=frozenset(), submit=False)

    assert len(runs.read_text().splitlines()) == 3
    assert world.step().done is True


def test_a_dry_run_changes_nothing_in_the_store(world: World) -> None:
    (world.tree / "flag").write_text("")
    world.wait_on(raised(passing_once_flagged(world)))
    before = world.store.get(UNIT)

    evaluate_manual_steps(world.inst, now=NOW, dry_run=True)

    assert world.store.get(UNIT) == before


# --- what a unit waiting on a step is -------------------------------------------------------


def test_a_unit_with_an_unmet_step_waits_on_manual_and_is_neither_failed_nor_held(
    world: World,
) -> None:
    world.wait_on(raised(passing_once_flagged(world)))
    world.evaluate()

    wait = world.waits()[UNIT]

    assert wait.reason is WaitReason.MANUAL == "manual"
    assert SLUG in wait.detail
    assert world.store.get(UNIT).state not in (FAILED, HELD)


def test_a_unit_waiting_on_a_step_keeps_its_slot(tmp_path: Path) -> None:
    world = make_world(tmp_path, slots=1)
    world.store.upsert([stored_unit("other/1", change="other")])
    world.wait_on(raised(passing_once_flagged(world)))

    waits = world.waits()

    assert waits[UNIT].reason is WaitReason.MANUAL
    assert waits["other/1"].reason is WaitReason.QUEUE_FULL


def test_the_status_names_the_step_the_last_line_and_the_runbook(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world.wait_on(raised(passing_once_flagged(world)))
    world.evaluate()

    lines = run_status(world.inst, monkeypatch, capsys)

    assert any(
        f"waiting for manual step {SLUG}: {MISSING} (runbook: {RUNBOOK})" in line for line in lines
    )


# --- the unit's own run ---------------------------------------------------------------------


def test_a_unit_with_a_declared_unmet_step_is_not_started_past_prepare(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.store.set_manual_steps(unit().id, (raised("exit 1"),))
    runtime = Sessions()

    tick(tmp_path, recorder, **agents(runtime))

    stored = recorder.store.get(unit().id)
    assert runtime.requests == []
    assert "push" not in recorder.events
    assert stored.state == PLANNED


class Raising(Sessions):
    """A builder that raises a step in its first call, as `abk manual raise` does."""

    def __init__(self, recorder: Any) -> None:
        super().__init__()
        self.recorder = recorder

    def run(self, request: Any) -> Any:
        if not self.requests:
            self.recorder.store.set_manual_steps(unit().id, (raised("exit 1"),))
        return super().run(request)


def test_a_unit_that_raises_a_step_mid_run_parks_as_waiting_and_is_not_failed(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    runtime = Raising(recorder)

    tick(tmp_path, recorder, **agents(runtime))

    stored = recorder.store.get(unit().id)
    assert stored.state == PLANNED and stored.state not in (FAILED, HELD)
    assert stored.cause is not Cause.FAILED
    assert "push" not in recorder.events


# --- abk manual check -----------------------------------------------------------------------


def test_manual_check_runs_every_check_now_or_only_the_one_named(
    world: World, tmp_path: Path
) -> None:
    other = raised(world.script("echo other; exit 1", "other.sh"), "other")
    world.wait_on(raised(passing_once_flagged(world)), other)
    config = world.inst.root / "abk.yaml"
    config.write_text(dump(world.inst.config))
    (world.tree / "flag").write_text("")

    assert main(["--config", str(config), "manual", "check", SLUG]) == 0
    only_one = (world.step(SLUG).done, world.step("other").outcome)
    assert main(["--config", str(config), "manual", "check"]) == 0

    assert only_one == (True, "")
    assert world.step("other").last_line == "other"


def test_manual_check_with_a_step_nobody_declared_is_refused(world: World) -> None:
    config = world.inst.root / "abk.yaml"
    config.write_text(dump(world.inst.config))

    assert main(["--config", str(config), "manual", "check", "no-such-step"]) != 0
