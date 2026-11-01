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
from agent_build_kit.pipeline.wiring import build_on_preexisting
from tests.e2e_wait_fakes import verdict_of
from tests.pipeline.test_flake_fix_change import (
    TEST,
    change_with_unit,
    changes,
    code_repo,
    flaked,
    waits_on,
)
from tests.regression_agent_fakes import waited_on as wait_on_fix
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
