"""Every test runs under a time limit that fails it from a thread (spec: flaky-tests).

A hung test must fail in a minute, naming the limit, and the run must go on. The plugin
is driven in a child pytest, over a test that busy-waits past a one second limit.

The limit is a CPU budget with a wall-clock backstop of five times it (spec: test-determinism).
`budget_for` gives a test's budgets from the item alone, `clock_fired` is the step the timer
thread takes at each poll and `exceeded_text` is the failure sentence, so those cases pass the
readings in and wait on no clock. The CPU-bound child scenarios in
`tests/child_modules/cpu_time_limit/` make the backstop unreachable (`tests/cpu_spin.py`), and one
of them proves the CPU of a child the test waits on counts.

A test marked `time_limit(<seconds>)` is held to that many seconds (spec:
ci-gives-npm-a-longer-timeout), and a `e2e` test to `--e2e-test-time-limit` (spec:
e2e-tests-have-their-own-time-limit). `limit_for` gives a test's limit from the item alone. The
marked-limit scenarios in `tests/child_modules/marked_time_limit/` swap `threading.Timer` for a
recorder, so no outcome there depends on how long anything takes.
"""

from __future__ import annotations

import pytest

from tests import time_limit
from tests.child_pytest import run_scenario
from tests.time_limit import Budget, CpuSnapshot

CPU_SCENARIO = "cpu_time_limit"
E2E_SCENARIO = "fast_and_e2e_time_limit"
MARKED_SCENARIO = "marked_time_limit"


def test_a_test_that_hangs_fails_naming_the_limit_and_the_run_goes_on(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester, CPU_SCENARIO, "hangs.py", "--test-time-limit=1", monkeypatch=monkeypatch
    )

    assert result.code == 1, result.output
    assert "1 failed, 1 passed" in result.output
    assert "exceeded the CPU time budget of 1 s" in result.output, result.output


def test_a_fixture_that_hangs_in_setup_or_teardown_is_an_error_naming_the_limit(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester, CPU_SCENARIO, "slow_fixtures.py", "--test-time-limit=1", monkeypatch=monkeypatch
    )

    output = result.output
    assert result.code == 1, output
    assert "2 passed, 2 errors" in output, output
    assert output.count("exceeded the CPU time budget of 1 s") >= 2, output
    assert "test setup exceeded" in output
    assert "test teardown exceeded" in output


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
    request.applymarker(pytest.mark.e2e)

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


def test_the_cpu_of_a_child_counts(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester, CPU_SCENARIO, "child_spins.py", "--test-time-limit=1", monkeypatch=monkeypatch
    )

    assert result.code == 1, result.output
    assert "exceeded the CPU time budget of 1 s" in result.output, result.output


def test_the_default_limit_is_a_minute() -> None:
    assert time_limit.DEFAULT_TEST_TIME_LIMIT == 60


def test_the_suite_runs_under_the_limit(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.pluginmanager.has_plugin("tests.time_limit")
    assert pytestconfig.getoption("--test-time-limit") == time_limit.DEFAULT_TEST_TIME_LIMIT


def test_a_time_limit_marker_gives_its_seconds(request: pytest.FixtureRequest) -> None:
    request.applymarker(pytest.mark.time_limit(5))

    assert time_limit.limit_for(request.node) == 5


def test_a_time_limit_marker_given_as_a_keyword_gives_its_seconds(
    request: pytest.FixtureRequest,
) -> None:
    request.applymarker(pytest.mark.time_limit(seconds=7))

    assert time_limit.limit_for(request.node) == 7


def test_an_unmarked_test_gets_the_fast_limit(request: pytest.FixtureRequest) -> None:
    expected = request.config.getoption("--test-time-limit")

    assert time_limit.limit_for(request.node) == expected


def test_an_e2e_test_keeps_the_e2e_limit_over_its_marker(
    request: pytest.FixtureRequest,
) -> None:
    request.applymarker(pytest.mark.e2e)
    request.applymarker(pytest.mark.time_limit(1))

    assert time_limit.limit_for(request.node) == time_limit.e2e_limit(request.config)


def test_a_e2e_test_slower_than_the_fast_limit_passes_in_call_setup_teardown_and_module_fixture(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester,
        E2E_SCENARIO,
        "slow_e2e.py",
        "--test-time-limit=1",
        "--e2e-test-time-limit=20",
        monkeypatch=monkeypatch,
    )

    assert result.code == 0, result.output
    assert "5 passed" in result.output, result.output
    assert "exceeded" not in result.output


def test_a_e2e_test_past_its_limit_fails_naming_the_e2e_limit(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester,
        E2E_SCENARIO,
        "hanging.py",
        "--test-time-limit=2",
        "--e2e-test-time-limit=1",
        monkeypatch=monkeypatch,
    )

    assert result.code == 1, result.output
    assert "e2e-test time limit of 1 seconds" in result.output, result.output


def test_a_test_without_the_marker_still_fails_at_the_fast_limit_with_the_old_message(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester,
        E2E_SCENARIO,
        "slow_both.py",
        "--test-time-limit=1",
        "--e2e-test-time-limit=20",
        monkeypatch=monkeypatch,
    )

    assert result.code == 1, result.output
    assert "1 failed, 1 passed" in result.output, result.output
    assert "FAILED slow_both.py::test_fast_is_slow" in result.output, result.output
    assert "test exceeded the CPU time budget of 1 s" in result.output, result.output
    assert "e2e-test" not in result.output, result.output


def test_the_e2e_limit_has_a_default_and_an_option(pytestconfig: pytest.Config) -> None:
    assert time_limit.DEFAULT_E2E_TEST_TIME_LIMIT == 30 * 60
    assert time_limit.e2e_limit(pytestconfig) == time_limit.DEFAULT_E2E_TEST_TIME_LIMIT


def test_a_e2e_limit_of_zero_turns_it_off_and_leaves_the_fast_limit(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester,
        E2E_SCENARIO,
        "slow_both.py",
        "--test-time-limit=1",
        "--e2e-test-time-limit=0",
        monkeypatch=monkeypatch,
    )

    assert "1 failed, 1 passed" in result.output, result.output
    assert "FAILED slow_both.py::test_fast_is_slow" in result.output, result.output
    assert "test exceeded the CPU time budget of 1 s" in result.output, result.output


def test_the_old_flag_still_limits_an_e2e_test_and_says_it_is_deprecated(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester,
        E2E_SCENARIO,
        "hanging.py",
        "--test-time-limit=2",
        time_limit.OLD_FLAG + "=1",
        monkeypatch=monkeypatch,
    )

    assert result.code == 1, result.output
    assert "e2e-test time limit of 1 seconds" in result.output, result.output
    deprecation = f"{time_limit.OLD_FLAG} is deprecated; use {time_limit.NEW_FLAG}"
    assert deprecation in result.output, result.output


def test_setting_the_old_and_the_new_flag_is_refused_naming_both(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester,
        E2E_SCENARIO,
        "hanging.py",
        time_limit.OLD_FLAG + "=1",
        time_limit.NEW_FLAG + "=1",
        monkeypatch=monkeypatch,
    )

    assert result.code != 0, result.output
    assert time_limit.OLD_FLAG in result.output, result.output
    assert time_limit.NEW_FLAG in result.output, result.output


def test_an_e2e_test_with_a_time_limit_marker_keeps_the_e2e_limit(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester,
        E2E_SCENARIO,
        "marked_e2e.py",
        "--test-time-limit=20",
        "--e2e-test-time-limit=2",
        monkeypatch=monkeypatch,
    )

    assert result.code == 1, result.output
    assert "e2e-test time limit of 2 seconds" in result.output, result.output


def test_a_marked_test_runs_past_the_default_and_passes(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = run_scenario(
        pytester,
        MARKED_SCENARIO,
        "reads_the_limit.py",
        "--test-time-limit=9000",
        "--e2e-test-time-limit=20",
        "-rA",
        monkeypatch=monkeypatch,
    ).output

    assert "PASSED reads_the_limit.py::test_marked_runs_past_the_default" in output, output
    assert "PASSED reads_the_limit.py::test_marked_runs_past_its_own_limit" in output, output
    assert "PASSED reads_the_limit.py::test_unmarked_beside_them" in output, output
    assert "exceeded" not in output, output


def test_a_marked_test_past_its_own_limit_fails_naming_that_limit(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = run_scenario(
        pytester,
        MARKED_SCENARIO,
        "blocks.py",
        "--test-time-limit=20",
        "--e2e-test-time-limit=20",
        env={"CHILD_FIRE_FIRST_TIMER": "1"},
        monkeypatch=monkeypatch,
    ).output

    assert "FAILED blocks.py::test_marked_runs_past_its_own_limit" in output, output
    assert "test exceeded the wall-clock backstop of 5 s" in output, output


def test_an_unmarked_test_beside_a_marked_one_still_fails_at_the_default(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = run_scenario(
        pytester,
        MARKED_SCENARIO,
        "blocks.py",
        "--test-time-limit=20",
        "--e2e-test-time-limit=20",
        env={"CHILD_FIRE_FIRST_TIMER": "1"},
        monkeypatch=monkeypatch,
    ).output

    assert "FAILED blocks.py::test_unmarked_beside_them" in output, output
    assert "test exceeded the wall-clock backstop of 100 s" in output, output
    assert "2 failed" in output, output


def snapshot(
    main: float = 0.0,
    tasks: dict[int, float] | None = None,
    descendants: dict[int, float] | None = None,
    reaped: float = 0.0,
) -> CpuSnapshot:
    return CpuSnapshot(main=main, tasks=tasks or {}, descendants=descendants or {}, reaped=reaped)


def test_a_thread_alive_before_the_phase_adds_no_cpu_to_it() -> None:
    start = snapshot(main=1, tasks={7: 100})

    assert time_limit.phase_cpu(start, snapshot(main=1, tasks={7: 150})) == 0


def test_a_descendant_alive_before_the_phase_adds_no_cpu_to_it() -> None:
    start = snapshot(descendants={9: 10})

    assert time_limit.phase_cpu(start, snapshot(descendants={9: 60})) == 0


@pytest.mark.parametrize(
    ("now", "seconds"),
    [
        (snapshot(main=5, tasks={7: 100}, descendants={9: 10}, reaped=1), 4),
        (snapshot(main=1, tasks={7: 100, 8: 3}, descendants={9: 10}, reaped=1), 3),
        (snapshot(main=1, tasks={7: 100}, descendants={9: 10, 10: 2}, reaped=1), 2),
        (snapshot(main=1, tasks={7: 100}, descendants={9: 10}, reaped=6.5), 5.5),
    ],
    ids=["main thread", "new task", "new descendant", "reaped children"],
)
def test_a_phase_counts_the_main_thread_what_it_started_and_what_children_gave(
    now: CpuSnapshot, seconds: float
) -> None:
    start = snapshot(main=1, tasks={7: 100}, descendants={9: 10}, reaped=1)

    assert time_limit.phase_cpu(start, now) == pytest.approx(seconds)


def test_an_inherited_thread_that_grew_is_named_with_the_test_that_left_it() -> None:
    start = snapshot(tasks={7: 100})
    now = snapshot(tasks={7: 150.5})

    lines = time_limit.inherited_lines(start, now, {7: ("thread poller", "tests/a.py::test_x")})

    assert len(lines) == 1
    assert "poller" in lines[0]
    assert "tests/a.py::test_x" in lines[0]
    assert "50.50" in lines[0]


def test_an_inherited_thread_nobody_recorded_is_named_as_left_by_an_earlier_test() -> None:
    lines = time_limit.inherited_lines(snapshot(tasks={7: 1}), snapshot(tasks={7: 2}), {})

    assert len(lines) == 1
    assert "an earlier test" in lines[0]


def test_an_inherited_thread_that_did_not_grow_has_no_line() -> None:
    start = snapshot(tasks={7: 100}, descendants={9: 3})

    assert time_limit.inherited_lines(start, start, {}) == []
