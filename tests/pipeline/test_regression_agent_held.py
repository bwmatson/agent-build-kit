"""A change the agent's run ended for a person to look at is held as work handed to someone
outside the kit: the planner leaves it alone, a unit waiting on it stays gated, and `abk status`
says why (spec: regression-agent).
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.external_file import (
    blocked_groups,
    held_units,
    hold_status_lines,
    release_holds,
)
from agent_build_kit.pipeline.flakes import flake_change_name
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.factories import stored_unit
from tests.pipeline.test_flake_fix_change import change_with_unit, code_repo, flaked
from tests.regression_agent_fakes import waited_on
from tests.regression_agent_support import TEST, UNDECIDED, Attempts
from tests.runtimes.stand_in import StandInRuntime

REASON = "the agent could not decide which side is wrong"


def parked(installation: Installation, store: UnitStore, uid: str) -> tuple[object, ...]:
    cli.link_needs(installation, store=store)
    cli.release_gated(installation, store)
    unit = store.get(uid)
    return unit.state, unit.cause, unit.gated_requeue


def waiting_store(installation: Installation) -> UnitStore:
    code_repo(installation)
    waiting = change_with_unit(installation, "feature", "feature/1")
    store = UnitStore(installation.root / "units.json")
    store.upsert([waiting])
    store.set_state(waiting.id, PLANNED, note="waiting for the fix", cause=Cause.GATED)
    store.set_gated_requeue(waiting.id, RequeueReason.RESUME)
    return store


def test_a_unit_waiting_on_a_held_change_with_no_tasks_stays_gated_until_it_is_gone(
    installation: Installation,
) -> None:
    store = waiting_store(installation)
    runtime = StandInRuntime(answer=f"I cannot tell.\n{UNDECIDED}\n")
    fix = flake_change_name(TEST)
    waited_on(installation, flaked(), store.get("feature/1"), runtime=runtime)
    held = (PLANNED, Cause.GATED, RequeueReason.RESUME)

    assert not (installation.changes_dir / fix / "tasks.md").exists()
    for _ in range(3):
        assert parked(installation, store, "feature/1") == held, "every tick, not just the first"

    shutil.rmtree(installation.changes_dir / fix)
    assert parked(installation, store, "feature/1")[2] is None, "released once the folder is gone"


def held_change_with_tasks(installation: Installation) -> tuple[str, UnitStore]:
    """A change the agent wrote in full and could not decide on, and a unit of it."""
    store = waiting_store(installation)
    fix = flake_change_name(TEST)
    agent = Attempts(installation, fix, {})
    agent.runtime.answer = f"Written anyway.\n{UNDECIDED}\n"
    waited_on(installation, flaked(), store.get("feature/1"), runtime=agent.runtime)
    store.upsert([stored_unit(f"{fix}/1", change=fix, groups=(1,))])
    return fix, store


def test_a_held_change_with_tasks_is_not_planned_until_a_person_gives_it_back(
    installation: Installation,
) -> None:
    fix, store = held_change_with_tasks(installation)
    folder = installation.changes_dir / fix

    assert (folder / "tasks.md").is_file()
    assert blocked_groups(folder) == frozenset({1}), "what the planner and the start path read"
    assert list(held_units(installation.changes_dir, [store.get(f"{fix}/1")])) == [f"{fix}/1"]

    release_holds(folder, [1])

    assert blocked_groups(folder) == frozenset()
    assert held_units(installation.changes_dir, [store.get(f"{fix}/1")]) == {}


def test_status_names_a_held_change_and_why(installation: Installation) -> None:
    fix, store = held_change_with_tasks(installation)

    lines = hold_status_lines(installation.changes_dir, store.all(), datetime.now(UTC))

    assert any(fix in line and REASON in line for line in lines)


@pytest.mark.parametrize("ok", [True, False], ids=["undecided", "failed"])
def test_a_second_unit_meeting_a_held_change_runs_nothing(
    installation: Installation, ok: bool
) -> None:
    store = waiting_store(installation)
    store.upsert([stored_unit("other/1", change="feature", groups=(1,))])
    runtime = StandInRuntime(
        ok=ok, answer=f"{UNDECIDED}\n" if ok else "", error="" if ok else "exit 1"
    )

    waited_on(installation, flaked(), store.get("feature/1"), runtime=runtime)
    waited_on(installation, flaked(unit="other/1"), store.get("other/1"), runtime=runtime)

    assert len(runtime.requests) == 1
