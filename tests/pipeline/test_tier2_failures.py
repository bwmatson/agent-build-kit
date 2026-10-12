"""The profile reads the first failure line of every failed or errored test from the
short summary, and the gate merges those of every project."""

from pathlib import Path

from agent_build_kit.config import ProjectConfig
from agent_build_kit.pipeline.tier2 import TestFailure
from agent_build_kit.profiles.node_npm import PROFILE as NODE
from agent_build_kit.profiles.python_uv import PROFILE as PYTHON
from tests.tier2_failure_fakes import (
    FIXTURE_LINE,
    FOUR_ERRORS,
    MIXED,
    NO_SUMMARY,
    NODE_OUTPUT,
    gate,
    run_returning,
)

UNIT = "tests/integration/test_unit.py"


def test_four_tests_erroring_on_one_fixture_are_four_entries() -> None:
    failures = PYTHON.parse_test_failures(FOUR_ERRORS)

    assert failures == [
        TestFailure(test=f"{UNIT}::{name}", line=FIXTURE_LINE)
        for name in ("test_built", "test_pushed", "test_refused", "test_report")
    ]


def test_failures_and_errors_are_listed_in_the_order_printed() -> None:
    failures = PYTHON.parse_test_failures(MIXED)

    assert failures == [
        TestFailure(
            test="tests/live/test_route.py::test_route",
            line="AssertionError: assert 404 == 200",
        ),
        TestFailure(test="tests/live/test_route.py::test_fixture", line="KeyError: 'PORT'"),
        TestFailure(test="tests/live/test_route.py::test_param[a b]", line="ValueError: bad route"),
    ]


def test_a_line_over_the_fixed_length_is_shortened_visibly() -> None:
    long = "RuntimeError: " + "x" * 2_000
    output = (
        f"=== short test summary info ===\nFAILED tests/t.py::test_a - {long}\n1 failed in 1s\n"
    )

    (failure,) = PYTHON.parse_test_failures(output)

    assert failure.test == "tests/t.py::test_a"
    assert len(failure.line) <= 500
    assert failure.line.startswith("RuntimeError: xxxx")
    assert failure.line != long
    assert failure.line.endswith(("…", "..."))


def test_an_output_with_no_failure_summary_gives_no_entries() -> None:
    assert PYTHON.parse_test_failures(NO_SUMMARY) == []


def test_a_node_profile_output_gives_no_entries() -> None:
    assert NODE.parse_test_failures(NODE_OUTPUT) == []


def _checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    for name in ("api", "web"):
        (root / name).mkdir(parents=True)
    return root


def test_the_gate_merges_the_failures_of_two_projects_in_order_labelled_by_project(
    tmp_path: Path,
) -> None:
    root = _checkout(tmp_path)
    session = gate(
        tmp_path,
        run_returning(MIXED, FOUR_ERRORS),
        projects=[ProjectConfig(path="api"), ProjectConfig(path="web")],
    )

    ok, snapshot = session.run(cwd=root)

    assert not ok
    assert session.result is not None
    tests = [failure.test for failure in session.result.failures]
    assert len(tests) == 3 + 4
    assert all("api" in test for test in tests[:3])
    assert all("web" in test for test in tests[3:])
    assert "tests/live/test_route.py::test_route" in tests[0]
    assert f"{UNIT}::test_report" in tests[-1]
    for test in tests:
        assert test in snapshot
    # the result is otherwise as before
    result = session.result
    assert (result.passed, result.failed) == (1 + 2, 2 + 1 + 4)
    assert result.output.count("$ ") == 2
    assert FIXTURE_LINE in result.output
