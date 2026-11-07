"""A test's time limit is a CPU budget with a wall-clock backstop (spec: test-determinism).

`budget_for` gives a test's budgets from the item alone, `clock_fired` is the step the timer
thread takes at each poll, and `exceeded_text` is the failure sentence, so none of them waits on
a clock: the readings are passed in. A child pytest over `tests/child_modules/cpu_time_limit/`
proves the plugin reads the CPU of the process and of a child it waits on.
"""

from __future__ import annotations

import pytest

from tests import time_limit
from tests.child_pytest import run_scenario
from tests.time_limit import Budget

SCENARIO = "cpu_time_limit"


def test_the_backstop_is_five_times_the_budget(request: pytest.FixtureRequest) -> None:
    request.applymarker(pytest.mark.time_limit(5))

    assert time_limit.budget_for(request.node) == Budget(cpu=5, wall=25)


def test_an_unmarked_test_has_the_default_as_its_cpu_budget(
    request: pytest.FixtureRequest,
) -> None:
    default = time_limit.DEFAULT_TEST_TIME_LIMIT

    assert time_limit.budget_for(request.node) == Budget(cpu=default, wall=default * 5)


def test_a_test_marked_with_the_loaded_limit_has_it_as_cpu_budget_and_five_times_as_backstop(
    request: pytest.FixtureRequest,
) -> None:
    request.applymarker(pytest.mark.time_limit(time_limit.LOADED_TEST_TIME_LIMIT))

    loaded = time_limit.LOADED_TEST_TIME_LIMIT
    assert time_limit.budget_for(request.node) == Budget(cpu=loaded, wall=loaded * 5)


def test_an_e2e_test_keeps_its_wall_clock_limit_and_has_no_cpu_budget(
    request: pytest.FixtureRequest,
) -> None:
    request.applymarker(pytest.mark.local_stack)

    budget = time_limit.budget_for(request.node)

    assert budget == Budget(cpu=0, wall=time_limit.e2e_limit(request.config))


def test_a_limit_of_zero_turns_both_clocks_off(request: pytest.FixtureRequest) -> None:
    request.applymarker(pytest.mark.time_limit(0))

    assert time_limit.budget_for(request.node) == Budget(cpu=0, wall=0)


def test_a_test_that_uses_more_cpu_than_its_budget_fires_the_cpu_clock() -> None:
    budget = Budget(cpu=60, wall=300)

    assert time_limit.clock_fired(budget, cpu_used=60.5, wall_elapsed=61) == "cpu"


def test_a_test_that_uses_no_cpu_fires_the_wall_clock_at_the_backstop() -> None:
    budget = Budget(cpu=60, wall=300)

    assert time_limit.clock_fired(budget, cpu_used=0, wall_elapsed=299) is None
    assert time_limit.clock_fired(budget, cpu_used=0, wall_elapsed=300.5) == "wall"


def test_a_test_starved_of_cpu_passes_until_the_backstop() -> None:
    budget = Budget(cpu=60, wall=300)

    assert time_limit.clock_fired(budget, cpu_used=12, wall_elapsed=250) is None


def test_an_e2e_budget_fires_only_on_wall_time() -> None:
    budget = Budget(cpu=0, wall=1800)

    assert time_limit.clock_fired(budget, cpu_used=5000, wall_elapsed=1000) is None
    assert time_limit.clock_fired(budget, cpu_used=5000, wall_elapsed=1801) == "wall"


def test_a_zero_budget_never_fires() -> None:
    budget = Budget(cpu=0, wall=0)

    assert time_limit.clock_fired(budget, cpu_used=1e6, wall_elapsed=1e6) is None


def test_the_cpu_failure_text_names_the_cpu_time_budget() -> None:
    text = time_limit.exceeded_text("cpu", Budget(cpu=60, wall=300))

    assert "exceeded the CPU time budget of 60 s" in text


def test_the_wall_failure_text_names_the_wall_clock_backstop() -> None:
    text = time_limit.exceeded_text("wall", Budget(cpu=60, wall=300))

    assert "exceeded the wall-clock backstop of 300 s" in text


def test_a_test_that_spins_fails_at_its_cpu_budget_naming_it(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester, SCENARIO, "spins.py", "--test-time-limit=1", monkeypatch=monkeypatch
    )

    assert result.code == 1, result.output
    assert "exceeded the CPU time budget of 1 s" in result.output, result.output


def test_the_cpu_of_a_child_counts(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester, SCENARIO, "child_spins.py", "--test-time-limit=1", monkeypatch=monkeypatch
    )

    assert result.code == 1, result.output
    assert "exceeded the CPU time budget of 1 s" in result.output, result.output
