"""A failure in a scoped moved-base run is isolated, and a flake in it does not hold the unit
(spec: a-moved-base-is-checked-by-what-it-can-affect).

The runner is the real one over a real repository, its commands faked at their boundary: a
command fails with the line a test runner prints and passes when it is run again alone. The
graph's `tier1` node and the merge handler are driven with a tier 1 that raises what the
runner raises. Each flake test is paired with a failure that repeats, so the two outcomes
are read side by side.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.flakes import Flake, FlakeFound, flake_record
from agent_build_kit.pipeline.restack import Moved
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED, Unit
from agent_build_kit.pipeline.wiring import build_on_flake, build_tier1
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.graph.test_build_path import build, restacked
from tests.graph.test_flake_parking import FLAKE, TEST
from tests.graph.test_fresh_base_builds import Moving
from tests.graph.test_remaining_paths import fresh
from tests.moved_base_fakes import moved
from tests.pipeline.test_flake_fix_change import (
    change_with_unit,
    changes,
    code_repo,
    waits_on,
)
from tests.pipeline.test_moved_base_selection import OWN_TEST, Runner, Selecting, run_moved

OTHER = "tests/test_other.py::test_x"
OWN = "tests/test_own.py::test_six"
OLD_BASE = "old-base-sha"
OWN_REPEAT = ["tests", OWN]
FILES: dict[str, Any] = {
    "own": {"a.py": "a = 2\n", "tests/test_own.py": OWN_TEST},
    "incoming": {"b.py": "b = 2\n"},
}


class Failing(Runner):
    """Fails `command` once with a failed-test line for `test`, and answers the same command
    run again alone for that test, serially, with `again`'s exit: 0, or 1 and the line."""

    def __init__(self, command: list[str], test: str, *, again: int) -> None:
        super().__init__()
        self.command = command
        self.test = test
        self.again = again
        self.failed = False

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        line = f"FAILED {self.test} - assert 1 == 2\n1 failed in 0.10s\n"
        if command == self.command and not self.failed:
            self.failed = True
            self.ran.append(command)
            return subprocess.CompletedProcess(command, 1, line, "")
        alone = command[: len(self.command)] == self.command and command[-1] == self.test
        if alone and len(command) > len(self.command):
            self.ran.append(command)
            return subprocess.CompletedProcess(command, self.again, line if self.again else "", "")
        return super().__call__(command, **kwargs)


def room(tmp_path: Path, name: str) -> Path:
    """A folder of its own under the test's, for a second scenario in one test."""
    path = tmp_path / name
    path.mkdir()
    return path


def scoped_flake(tmp_path: Path) -> FlakeFound:
    """What a scoped run raises when a test the unit did not add fails and passes alone."""
    runner = Failing(["affected"], OTHER, again=0)
    with pytest.raises(FlakeFound) as raised:
        run_moved(tmp_path, Selecting([["affected"]]), runner, **FILES)
    assert raised.value.scoped
    return raised.value


# --- the runner ---------------------------------------------------------------------


def test_a_scoped_test_that_passes_alone_raises_a_flake_marked_as_scoped(tmp_path: Path) -> None:
    runner = Failing(["affected"], OTHER, again=0)

    with pytest.raises(FlakeFound) as raised:
        run_moved(tmp_path, Selecting([["affected"]]), runner, **FILES)

    assert [flake.test for flake in raised.value.flakes] == [OTHER]
    assert raised.value.scoped
    assert ["tests"] not in runner.ran, "the full suite did not stand in for the flake"


def test_a_test_that_fails_again_alone_holds_where_a_flake_did_not(tmp_path: Path) -> None:
    scoped_flake(room(tmp_path, "flake"))
    runner = Failing(["affected"], OTHER, again=1)

    passed, _ = run_moved(room(tmp_path, "repeat"), Selecting([["affected"]]), runner, **FILES)

    assert not passed


def test_a_scoped_test_the_unit_added_that_passes_alone_is_a_real_failure(tmp_path: Path) -> None:
    runner = Failing(OWN_REPEAT, OWN, again=0)

    passed, logged = run_moved(tmp_path, Selecting([["affected"]]), runner, **FILES)

    assert not passed, "a new test has no excuse to be flaky"
    assert not [line for line in logged if "flak" in line.lower() and "moved base" in line]


def test_the_added_tests_are_repeated_over_the_same_ids_on_a_scoped_run_as_on_a_full_one(
    tmp_path: Path,
) -> None:
    scoped = Failing(["affected"], OTHER, again=0)
    with pytest.raises(FlakeFound) as raised:
        run_moved(room(tmp_path, "scoped"), Selecting([["affected"]]), scoped, **FILES)
    assert raised.value.scoped
    make_installation(tmp_path / "planning-full", limits={"tier1_repeat_runs": 1})
    repo, _ = moved(room(tmp_path, "full"), own=FILES["own"], incoming=FILES["incoming"])
    full = Runner()

    assert build_tier1(profile=Selecting(), run=full)(cwd=repo, base="main")[0]

    assert OWN_REPEAT in scoped.ran and OWN_REPEAT in full.ran
    assert scoped.failed, "the scoped run met its flake"


def test_a_full_run_under_the_full_setting_raises_its_flake_as_a_full_runs_flake(
    tmp_path: Path,
) -> None:
    scoped_flake(room(tmp_path, "scoped"))
    workspace = make_installation(
        tmp_path / "planning-full", limits={"tier1_repeat_runs": 1, "restack_check": "full"}
    )
    runner = Failing(["tests"], OTHER, again=0)

    with pytest.raises(FlakeFound) as raised:
        run_moved(room(tmp_path, "full"), Selecting(), runner, workspace=workspace, **FILES)

    assert not raised.value.scoped


# --- the graph ----------------------------------------------------------------------


class Told:
    """What the runner was told of each flake: the unit, the test and whether it waits."""

    def __init__(self) -> None:
        self.flakes: list[tuple[str, str, bool]] = []

    def __call__(self, unit: Unit, flake: Flake, *, wait: bool = True) -> str | None:
        self.flakes.append((unit.id, flake.test, wait))
        return "fix-flaky-widget"


class Raising:
    """Tier 1 that raises a flake on its second run, the one after the move, and otherwise
    answers as the recorder's."""

    def __init__(self, recorder: Any, *, scoped: bool) -> None:
        self.recorder = recorder
        self.scoped = scoped
        self.runs = 0

    def __call__(self, **kwargs: Any) -> tuple[bool, str]:
        self.runs += 1
        if self.runs == 2:
            self.recorder.events.append("tier1")
            raise FlakeFound((FLAKE,), scoped=self.scoped)
        return self.recorder.tier1(**kwargs)


def moved_build(
    tmp_path: Path, name: str, told: Told, *, scoped: bool, **options: Any
) -> tuple[Any, RunOutcome]:
    """A unit built to its move in a folder `name`, its second tier 1 raising a flake that is
    `scoped` or not; returns the recorder and the outcome."""
    where = room(tmp_path, name)
    recorder = fresh(where, **options)
    moving = Moving(recorder, restacked(old_base=OLD_BASE))
    return recorder, build(
        where,
        recorder,
        run_tier1=Raising(recorder, scoped=scoped),
        on_flake=told,
        **moving.overrides(),
    )


def test_a_scoped_flake_on_a_moved_base_is_recorded_and_the_unit_goes_on_to_its_push(
    tmp_path: Path,
) -> None:
    told = Told()

    recorder, outcome = moved_build(tmp_path, "flake", told, scoped=True)

    assert told.flakes == [("add-marker/1", TEST, False)]
    assert outcome.status == "open"
    stored = recorder.store.get("add-marker/1")
    assert stored.cause is not Cause.GATED and stored.gated_requeue is None
    assert "push" in recorder.events
    assert not {"claude:rework", "claude:fix_checks"} & set(recorder.events)


def test_a_failure_that_repeats_holds_the_unit_where_a_scoped_flake_did_not(
    tmp_path: Path,
) -> None:
    moved_build(tmp_path, "flake", Told(), scoped=True)
    where = room(tmp_path, "held")
    held = fresh(where)
    held.tier1_results = [(True, ""), (False, "FAILED tests/test_x.py::test_y - assert 1 == 2")]
    told = Told()

    build(where, held, on_flake=told, **Moving(held, restacked(old_base=OLD_BASE)).overrides())

    assert told.flakes == []
    assert "push" not in held.events
    assert "test_y" in held.store.get("add-marker/1").feedback


def test_a_flake_of_a_full_run_still_parks_the_unit_beside_a_scoped_one_that_does_not(
    tmp_path: Path,
) -> None:
    scoped, _ = moved_build(tmp_path, "scoped", Told(), scoped=True)
    told = Told()

    recorder, outcome = moved_build(tmp_path, "full", told, scoped=False)

    assert scoped.store.get("add-marker/1").cause is not Cause.GATED
    assert outcome.status == RunStatus.HELD
    assert told.flakes == [("add-marker/1", TEST, True)]
    stored = recorder.store.get("add-marker/1")
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED)


def test_a_tier_two_unit_runs_tier_2_after_a_scoped_flake_and_is_told_of_it_once(
    tmp_path: Path,
) -> None:
    told = Told()

    recorder, outcome = moved_build(tmp_path, "flake", told, scoped=True, tier="tier2")

    assert outcome.status == "open"
    after = recorder.events[recorder.events.index("moved") :]
    assert after.index("tier1") < after.index("tier2") < after.index("push")
    assert told.flakes == [("add-marker/1", TEST, False)]


# --- the merge handler --------------------------------------------------------------


def restacking(installation: Installation, name: str, tier1: Any):
    """The handler over unit `name`, with the real flake recorder; returns the store, the
    pushes and the run."""
    child = change_with_unit(installation, name, f"{name}/1").model_copy(
        update={"pr": 2, "branch": f"spec/{name}/1", "approved": "approved"}
    )
    store = UnitStore(installation.root / f"{name}.json")
    store.upsert([child])
    pushed: list[str] = []
    restack = events.build_restack(
        repos={"app": installation.checkouts["app"]},
        store=store,
        root=installation.root,
        move=lambda *a, **k: Moved(sha="newsha"),
        tier1=tier1,
        on_flake=build_on_flake(store, installation, log=lambda message: None),
        push=lambda *a, **k: pushed.append("pushed") or "newsha",
        retarget=lambda *a, **k: None,
        comment=lambda *a, **k: None,
        diff_id=lambda repo, base, branch: "same-diff",
        head_of=lambda repo, branch: "approved",
    )

    def run() -> None:
        restack(
            branch=f"spec/{name}/1",
            old_base="spec/parent/1",
            new_base="main",
            child=child,
            parent=stored_unit("parent/1", change="parent", pr=1, branch="spec/parent/1"),
        )

    return store, pushed, run


def flaking(scoped: bool):
    def tier1(**kwargs: object):
        raise FlakeFound((FLAKE,), scoped=scoped)

    return tier1


def test_a_scoped_flake_met_by_the_handler_is_recorded_and_the_branch_is_pushed(
    installation: Installation,
) -> None:
    code_repo(installation)
    store, pushed, run = restacking(installation, "feature", flaking(scoped=True))

    run()

    (recorded,) = flake_record(installation).entries()
    assert (recorded.test, recorded.unit) == (TEST, "feature/1")
    assert recorded.change in changes(installation), "the one fix change was written"
    assert waits_on(installation, "feature") == []
    assert pushed == ["pushed"]
    assert store.get("feature/1").cause is not Cause.GATED


def test_a_failure_that_repeats_fails_the_handler_where_a_scoped_flake_did_not(
    installation: Installation,
) -> None:
    code_repo(installation)
    _, pushed, run = restacking(installation, "feature", flaking(scoped=True))
    run()
    _, held, rerun = restacking(
        installation, "other", lambda **k: (False, "FAILED tests/test_x.py::test_y")
    )

    with pytest.raises(RuntimeError, match="checks fail"):
        rerun()

    assert pushed == ["pushed"] and held == []


def test_a_flake_of_a_full_run_still_parks_the_child_beside_a_scoped_one_that_does_not(
    installation: Installation,
) -> None:
    code_repo(installation)
    _, pushed, run = restacking(installation, "feature", flaking(scoped=True))
    run()
    store, held, parked = restacking(installation, "other", flaking(scoped=False))

    parked()

    assert pushed == ["pushed"] and held == []
    assert waits_on(installation, "other") == [flake_record(installation).entries()[0].change]
    assert store.get("other/1").cause is Cause.GATED
