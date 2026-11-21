"""A failure the hour's cap holds back is still recorded, with the kind and no change, and the
failures after it are met too; and a directory a dead run left is written again (spec:
regression-agent)."""

from __future__ import annotations

import shutil
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import events, spans
from agent_build_kit.pipeline.flakes import FlakeFound, flake_change_name, flake_record
from agent_build_kit.pipeline.regression_agent import RUNS_FILE
from agent_build_kit.pipeline.restack import Moved
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.untouched_failures import preexisting_record
from agent_build_kit.pipeline.wiring import build_on_flake, build_on_preexisting
from tests.conftest import make_installation
from tests.e2e_wait_fakes import OLD, OTHER_OLD, OWN, Failing, snapshot_of, verdict_of
from tests.factories import stored_unit
from tests.graph_driver import fresh, tick
from tests.pipeline.test_flake_fix_change import (
    TASKS,
    TEST,
    change_with_unit,
    code_repo,
    flaked,
    waits_on,
)
from tests.regression_agent_fakes import DefaultAgent, waited_on
from tests.runtimes.stand_in import StandInRuntime

OTHER = "tests/test_widget.py::test_something_else"


def full_hour(installation: Installation) -> None:
    """The one run the cap of one allows has been started a few minutes ago."""
    at = spans.clock.now() - timedelta(minutes=5)
    (installation.state_dir / RUNS_FILE).parent.mkdir(parents=True, exist_ok=True)
    (installation.state_dir / RUNS_FILE).write_text(at.isoformat() + "\n")


def test_two_flakes_of_a_scoped_moved_base_run_are_both_recorded_when_the_cap_holds_them(
    tmp_path: Path,
) -> None:
    installation = make_installation(tmp_path, global_limits=dict(max_regression_runs_per_hour=1))
    code_repo(installation)
    child = change_with_unit(installation, "feature", "feature/1").model_copy(
        update={"pr": 2, "branch": "spec/feature/1", "approved": "approved"}
    )
    store = UnitStore(installation.root / "units.json")
    store.upsert([child])
    full_hour(installation)
    pushed: list[str] = []

    def scoped(**kwargs: object):
        raise FlakeFound((flaked(TEST), flaked(OTHER)), scoped=True)

    restack = events.build_restack(
        repos={"app": installation.checkouts["app"]},
        store=store,
        root=installation.root,
        move=lambda *a, **k: Moved(sha="newsha"),
        unit_test=scoped,
        on_flake=build_on_flake(store, installation, log=lambda message: None),
        push=lambda *a, **k: pushed.append("pushed") or "newsha",
        retarget=lambda *a, **k: None,
        comment=lambda *a, **k: None,
        diff_id=lambda repo, base, branch: "same-diff",
        head_of=lambda repo, branch: "approved",
    )
    restack(
        branch="spec/feature/1",
        old_base="spec/parent/1",
        new_base="main",
        child=child,
        parent=stored_unit("parent/1", change="parent", pr=1, branch="spec/parent/1"),
    )

    rows = flake_record(installation).entries()
    assert [(row.test, row.fix_kind, row.change) for row in rows] == [
        (TEST, "flaky", ""),
        (OTHER, "flaky", ""),
    ]
    assert pushed == ["pushed"], "the branch goes on"


def test_pre_existing_failures_the_cap_holds_are_all_recorded_when_the_unit_does_not_wait(
    tmp_path: Path,
) -> None:
    installation = make_installation(tmp_path, global_limits=dict(max_regression_runs_per_hour=1))
    recorder = fresh(tmp_path)
    tasks = installation.changes_dir / "add-marker" / "tasks.md"
    tasks.parent.mkdir(parents=True)
    tasks.write_text(TASKS)
    recorder.store.upsert([stored_unit("add-marker/1", groups=(1,))])
    full_hour(installation)
    agent = DefaultAgent()
    e2e = Failing(
        recorder.events,
        snapshot_of(OWN, OLD, OTHER_OLD),
        verdict_of(own=(OWN,), old=(OLD, OTHER_OLD)),
    )

    outcome = tick(
        tmp_path,
        recorder,
        tier="e2e-test",
        run_e2e=e2e.run,
        e2e_verdict=e2e.judged,
        on_preexisting=build_on_preexisting(
            recorder.store, installation, runtime=agent.runtime, log=lambda message: None
        ),
    )

    rows = preexisting_record(installation).entries()
    assert [(row.test, row.fix_kind, row.change) for row in rows] == [
        (OLD, "pre-existing", ""),
        (OTHER_OLD, "pre-existing", ""),
    ]
    assert agent.runtime.requests == []
    assert outcome.status != RunStatus.HELD, "its own failure fails it as it would"


# --- a directory a dead run left ----------------------------------------------------


@pytest.mark.parametrize("left", [None, "proposal.md"], ids=["empty", "proposal-only"])
def test_a_directory_a_dead_run_left_is_written_again(
    installation: Installation, left: str | None, no_real_regression_agent: DefaultAgent
) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")
    fix = flake_change_name(TEST)
    (installation.changes_dir / fix).mkdir()
    if left:
        (installation.changes_dir / fix / left).write_text("## Why\n\nhalf written\n")

    named = waited_on(installation, flaked(), unit)

    assert named == fix
    assert len(no_real_regression_agent.runtime.requests) == 1
    assert (installation.changes_dir / fix / "tasks.md").is_file()
    assert waits_on(installation, "feature") == [fix]


# --- a run that ended held for a person ---------------------------------------------


@pytest.mark.parametrize(
    "runtime",
    [
        StandInRuntime(answer="I cannot tell.\nJUDGEMENT: undecided\n"),
        StandInRuntime(ok=False, error="exit 1"),
    ],
    ids=["undecided", "failed"],
)
def test_a_change_held_for_a_person_is_waited_on_and_the_agent_is_not_run_again(
    installation: Installation, runtime: StandInRuntime
) -> None:
    code_repo(installation)
    units = [
        change_with_unit(installation, "feature", "feature/1"),
        change_with_unit(installation, "other", "other/1"),
    ]
    fix = flake_change_name(TEST)

    named = [waited_on(installation, flaked(unit=u.id), u, runtime=runtime) for u in units]

    assert named == [fix, fix]
    assert len(runtime.requests) == 1
    assert not (installation.changes_dir / fix / "tasks.md").exists()
    assert waits_on(installation, "feature") == [fix]
    assert waits_on(installation, "other") == [fix]
    assert len((installation.state_dir / RUNS_FILE).read_text().split()) == 1


def test_a_held_change_a_person_removed_is_written_again(installation: Installation) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")
    runtime = StandInRuntime(ok=False, error="exit 1")
    fix = flake_change_name(TEST)
    waited_on(installation, flaked(), unit, runtime=runtime)
    shutil.rmtree(installation.changes_dir / fix)

    waited_on(installation, flaked(), unit)

    assert (installation.changes_dir / fix / "tasks.md").is_file()


def test_a_unit_of_the_fix_change_that_meets_its_own_test_is_told_even_when_another_is_capped(
    tmp_path: Path,
) -> None:
    installation = make_installation(tmp_path, global_limits=dict(max_regression_runs_per_hour=1))
    code_repo(installation)
    own = flake_change_name(TEST)
    child = change_with_unit(installation, own, f"{own}/1").model_copy(
        update={"pr": 2, "branch": f"spec/{own}/1", "approved": "approved"}
    )
    store = UnitStore(installation.root / "units.json")
    store.upsert([child])
    full_hour(installation)

    def scoped(**kwargs: object):
        raise FlakeFound((flaked(TEST), flaked(OTHER)), scoped=True)

    restack = events.build_restack(
        repos={"app": installation.checkouts["app"]},
        store=store,
        root=installation.root,
        move=lambda *a, **k: Moved(sha="newsha"),
        unit_test=scoped,
        on_flake=build_on_flake(store, installation, log=lambda message: None),
        push=lambda *a, **k: "newsha",
        retarget=lambda *a, **k: None,
        comment=lambda *a, **k: None,
        diff_id=lambda repo, base, branch: "same-diff",
        head_of=lambda repo, branch: "approved",
    )

    with pytest.raises(RuntimeError, match="checks fail"):
        restack(
            branch=child.branch,
            old_base="spec/parent/1",
            new_base="main",
            child=child,
            parent=stored_unit("parent/1", change="parent", pr=1, branch="spec/parent/1"),
        )
