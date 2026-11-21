"""Every change that fixes a failing test is named `fix-test-<slug>`, whatever the kind of the
failure, and one lookup by the test's identifier finds an open change of any of the three
prefixes (spec: regression-agent).
"""

from __future__ import annotations

import re

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import (
    FIX_PREFIX,
    fix_change_name,
    next_fix_name,
    open_fix_change,
)
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.wiring import build_on_preexisting
from tests.e2e_wait_fakes import verdict_of
from tests.factories import stored_unit
from tests.pipeline.test_flake_fix_change import (
    TEST,
    change_with_unit,
    changes,
    code_repo,
    flaked,
    waits_on,
)
from tests.regression_agent_fakes import waited_on as wait_on_fix
from tests.regression_agent_support import Attempts
from tests.untouched_failure_fakes import TEST as RECORDED

PREFIXES = ["fix-test", "fix-flaky", "fix-failing"]


def open_change(inst: Installation, prefix: str, test: str = TEST) -> str:
    name = fix_change_name(test, prefix)
    (inst.changes_dir / name).mkdir(parents=True)
    return name


def test_a_new_flake_fix_is_named_fix_test(installation: Installation) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")

    name = wait_on_fix(installation, flaked(), unit)

    assert name is not None
    assert re.fullmatch(r"fix-test-[a-z0-9-]+", name)
    assert "test-renders-the-label" in name


def test_a_new_pre_existing_fix_is_named_fix_test(installation: Installation) -> None:
    code_repo(installation)
    first = change_with_unit(installation, "feature", "feature/1")
    store = UnitStore(installation.root / "units.json")
    store.upsert([first])
    verdict = verdict_of(old=(RECORDED,))
    (failed,) = verdict.pre_existing

    name = build_on_preexisting(store, installation, log=lambda message: None)(
        first, verdict, failed, wait=True
    )

    assert name is not None and name.startswith("fix-test-")


def test_both_kinds_for_one_test_are_one_name(installation: Installation) -> None:
    code_repo(installation)
    first = change_with_unit(installation, "feature", "feature/1")
    second = change_with_unit(installation, "other", "other/1")

    flake_fix = wait_on_fix(installation, flaked(), first)
    again = wait_on_fix(installation, flaked(unit="other/1"), second)

    assert flake_fix == again
    assert [c for c in changes(installation) if c.startswith("fix-")] == [flake_fix]


@pytest.mark.parametrize("prefix", PREFIXES)
def test_one_lookup_by_test_id_finds_the_open_change_of_every_prefix(
    installation: Installation, prefix: str
) -> None:
    name = open_change(installation, prefix)

    assert open_fix_change(installation, TEST) == (name, "")


@pytest.mark.parametrize("prefix", ["fix-flaky", "fix-failing"])
def test_a_failure_with_an_open_old_named_fix_waits_on_it_and_writes_no_second_change(
    installation: Installation, prefix: str
) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")
    old = open_change(installation, prefix)
    before = changes(installation)

    name = wait_on_fix(installation, flaked(), unit)

    assert name == old
    assert changes(installation) == before
    assert waits_on(installation, "feature") == [old]


def test_the_lookup_does_not_find_another_tests_change(installation: Installation) -> None:
    open_change(installation, FIX_PREFIX, "tests/test_widget.py::test_other")

    assert open_fix_change(installation, TEST) == (None, "")


def test_a_second_failure_after_an_archived_fix_takes_the_next_name(
    installation: Installation,
) -> None:
    archived = fix_change_name(TEST, FIX_PREFIX)
    (installation.changes_dir / "archive" / f"2026-03-01-{archived}").mkdir(parents=True)

    assert open_fix_change(installation, TEST) == (None, archived)
    assert next_fix_name(installation, TEST) == f"{archived}-2"


NOTE = "is no longer in the tree"
FINISHED = [UnitState.SATISFIED, UnitState.MERGED, UnitState.CLOSED, UnitState.RETIRED]


def fix_unit(inst: Installation, name: str, *states: tuple[UnitState, str]) -> None:
    """A fix change `name`, open under the changes directory, with one stored unit for each of
    `states` (the state and the note it was left with)."""
    (inst.changes_dir / name).mkdir(parents=True, exist_ok=True)
    store = UnitStore(inst.state_dir / "units.json")
    for number, (state, note) in enumerate(states, start=1):
        unit_id = f"{name}/{number}"
        store.upsert([stored_unit(unit_id, change=name, groups=(number,))])
        store.set_state(unit_id, state, note=note)


@pytest.mark.parametrize("state", FINISHED)
def test_a_fix_change_whose_units_all_finished_is_not_open_for_its_test(
    installation: Installation, state: UnitState
) -> None:
    name = fix_change_name(TEST, FIX_PREFIX)
    fix_unit(installation, name, (state, NOTE))

    assert open_fix_change(installation, TEST) == (None, name)
    assert next_fix_name(installation, TEST) == f"{name}-2"


def test_a_fix_change_with_one_unit_not_finished_is_open_beside_a_finished_earlier_one(
    installation: Installation,
) -> None:
    first = fix_change_name(TEST, FIX_PREFIX)
    second = f"{first}-2"
    fix_unit(installation, first, (UnitState.SATISFIED, NOTE))
    fix_unit(installation, second, (UnitState.SATISFIED, NOTE), (UnitState.RUNNING, ""))

    assert open_fix_change(installation, TEST) == (second, first)


def test_a_fix_change_with_no_stored_unit_is_open_beside_a_finished_earlier_one(
    installation: Installation,
) -> None:
    first = fix_change_name(TEST, FIX_PREFIX)
    second = f"{first}-2"
    fix_unit(installation, first, (UnitState.MERGED, NOTE))
    (installation.changes_dir / second).mkdir()

    assert open_fix_change(installation, TEST) == (second, first)


def test_a_failing_unit_waits_on_a_new_change_naming_the_finished_one_and_its_note(
    installation: Installation,
) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")
    finished = fix_change_name(TEST, FIX_PREFIX)
    fix_unit(installation, finished, (UnitState.SATISFIED, NOTE))
    new = f"{finished}-2"
    agent = Attempts(installation, new, {})

    name = wait_on_fix(installation, flaked(), unit, runtime=agent.runtime)

    assert name == new
    assert waits_on(installation, "feature") == [new]
    prompt = agent.runtime.request.prompt
    assert finished in prompt
    assert "satisfied" in prompt and NOTE in prompt
