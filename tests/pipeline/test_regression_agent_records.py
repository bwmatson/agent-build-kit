"""What the handlers record when the regression agent is asked: the kind of the failure on each
row, the change on the earlier rows of the test, and the earlier archived change in the agent's
prompt (spec: regression-agent)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.flakes import FailedOnBase, fix_change_name, flake_record
from agent_build_kit.pipeline.untouched_failures import preexisting_record
from agent_build_kit.pipeline.wiring import build_on_flake, build_on_preexisting
from tests.e2e_gate_fakes import Planning
from tests.e2e_wait_fakes import OLD, verdict_of
from tests.graph.test_failed_on_base_callers import FAILING as MET
from tests.pipeline.test_flake_fix_change import flaked
from tests.regression_agent_fakes import DefaultAgent
from tests.untouched_failure_fakes import failing

UNIT = "add-marker/1"
# A failure of a test the unit did not write, as unit-test raises it when it fails on the base.
FAILING = FailedOnBase((MET,)).failures[0]


def quietly(planning: Planning):
    return build_on_flake(planning.store, planning.installation, log=lambda message: None)


def test_a_flake_a_failure_on_the_base_and_a_pre_existing_failure_each_record_their_kind(
    tmp_path: Path,
) -> None:
    planning = Planning(tmp_path)
    unit = planning.store.get(UNIT)
    on_flake = quietly(planning)
    verdict = verdict_of(old=(OLD,))

    on_flake(unit, flaked())
    on_flake(unit, FAILING)
    build_on_preexisting(planning.store, planning.installation, log=lambda message: None)(
        unit, verdict, verdict.pre_existing[0], wait=False
    )

    rows = flake_record(planning.installation).entries()
    assert [(row.failing, row.fix_kind) for row in rows] == [
        (False, "flaky"),
        (True, "regression"),
    ]
    (pre_existing,) = preexisting_record(planning.installation).entries()
    assert pre_existing.fix_kind == "pre-existing"


def test_a_failure_the_base_run_showed_is_pre_existing_and_one_by_its_time_limit_is_a_regression(
    tmp_path: Path, no_real_regression_agent: DefaultAgent
) -> None:
    planning = Planning(tmp_path)
    unit = planning.store.get(UNIT)
    on_base = FAILING.model_copy(update={"base_output": "FAILED on the base"})
    by_time = FAILING.model_copy(update={"test": "tests/test_widget.py::test_slow"})

    quietly(planning)(unit, on_base)
    quietly(planning)(unit, by_time)

    assert [row.fix_kind for row in flake_record(planning.installation).entries()] == [
        "pre-existing",
        "regression",
    ]
    # What each change's agent was told, however many requests it took to get the change
    # accepted: a rewrite after a refusal asks again with the same kind.
    told: dict[str | None, set[str]] = {}
    for request in no_real_regression_agent.runtime.requests:
        kind = request.prompt.split("Kind of failure: ")[1].split()[0]
        told.setdefault(request.change, set()).add(kind)
    assert told == {
        fix_change_name(MET.test, "fix-test"): {"pre-existing"},
        fix_change_name(by_time.test, "fix-test"): {"regression"},
    }


def test_a_failure_on_the_base_is_recorded_and_leaves_the_flake_list_alone(
    tmp_path: Path,
) -> None:
    planning = Planning(tmp_path)

    quietly(planning)(planning.store.get(UNIT), FAILING)

    (row,) = flake_record(planning.installation).entries()
    assert row.failing and row.change == fix_change_name(FAILING.test, "fix-test")
    assert [
        c.test for c in flake_record(planning.installation).counts(lambda e: not e.failing)
    ] == []


def test_the_earlier_rows_of_the_test_name_the_change_once_it_is_written(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    record = preexisting_record(planning.installation)
    record.append(failing(OLD, unit="older/1"))
    record.append(failing("tests/far/test_other.py::test_other", unit="older/2"))
    flakes = flake_record(planning.installation)
    flakes.append(flaked(OLD, unit="older/3"))
    verdict = verdict_of(old=(OLD,))

    fix = build_on_preexisting(planning.store, planning.installation, log=lambda message: None)(
        planning.store.get(UNIT), verdict, verdict.pre_existing[0], wait=False
    )

    changes = {row.test: row.change for row in record.entries()}
    assert changes[OLD] == fix, "the earlier row of the test"
    assert [row.change for row in record.entries() if row.test == OLD] == [fix, fix]
    assert changes["tests/far/test_other.py::test_other"] == "", "another test's row is left"
    assert [row.change for row in flakes.entries()] == [fix], "in the other record too"


def test_a_test_with_a_change_already_named_on_a_row_keeps_it(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    record = preexisting_record(planning.installation)
    record.append(failing(OLD, unit="older/1", change="fix-test-archived-attempt"))
    verdict = verdict_of(old=(OLD,))

    build_on_preexisting(planning.store, planning.installation, log=lambda message: None)(
        planning.store.get(UNIT), verdict, verdict.pre_existing[0], wait=False
    )

    assert record.entries()[0].change == "fix-test-archived-attempt"


def test_the_earlier_archived_change_is_in_the_agents_prompt(
    tmp_path: Path, no_real_regression_agent: DefaultAgent
) -> None:
    planning = Planning(tmp_path)
    on_flake = quietly(planning)
    unit = planning.store.get(UNIT)
    first = on_flake(unit, FAILING)
    assert first
    archive = planning.installation.changes_dir / "archive"
    archive.mkdir()
    (planning.installation.changes_dir / first).rename(archive / f"2026-03-02-{first}")

    successor = on_flake(unit, FAILING)

    assert successor and successor != first
    prompt = no_real_regression_agent.runtime.requests[-1].prompt
    assert f"`{first}`" in prompt and "MODIFIED" in prompt


def test_a_first_failure_has_no_earlier_change_in_the_prompt(
    tmp_path: Path, no_real_regression_agent: DefaultAgent
) -> None:
    planning = Planning(tmp_path)

    quietly(planning)(planning.store.get(UNIT), FAILING)

    assert "merged and archived" not in no_real_regression_agent.runtime.request.prompt
