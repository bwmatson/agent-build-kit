"""Every test runs under a time limit that fails it from a thread (spec: flaky-tests).

A hung test must fail in a minute, naming the limit, and the run must go on. The plugin
is driven in a child pytest, over a test that busy-waits past a one second limit.

The limit is a CPU budget with a wall-clock backstop of five times it (spec: test-determinism).
`budget_for` gives a test's budgets from the item alone, `clock_fired` is the step the timer
thread takes at each poll and `exceeded_text` is the failure sentence, so those cases pass the
readings in and wait on no clock. The CPU-bound child scenarios in
`tests/child_modules/cpu_time_limit/` set `time_limit_backstop_factor` in their `pytest.ini`,
and one of them proves the CPU of a child the test waits on counts.

A test marked `time_limit(<seconds>)` is held to that many seconds (spec:
ci-gives-npm-a-longer-timeout), and a `e2e` test to `--e2e-test-time-limit` (spec:
e2e-tests-have-their-own-time-limit). `limit_for` gives a test's limit from the item alone. The
marked-limit scenarios in `tests/child_modules/marked_time_limit/` swap `threading.Timer` for a
recorder, so no outcome there depends on how long anything takes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests import time_limit
from tests.child_pytest import run_scenario
from tests.time_limit import Budget, CpuSnapshot, PhaseTrace

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
    process: float = 0.0,
    tasks: dict[int, float] | None = None,
    descendants: dict[int, float] | None = None,
    reaped: float = 0.0,
    children: frozenset[int] = frozenset(),
) -> CpuSnapshot:
    return CpuSnapshot(
        process=process,
        tasks=tasks or {},
        descendants=descendants or {},
        reaped=reaped,
        children=children,
    )


def test_a_thread_alive_before_the_phase_adds_no_cpu_to_it() -> None:
    start = snapshot(process=101, tasks={7: 100})

    assert time_limit.phase_cpu(start, snapshot(process=151, tasks={7: 150})) == 0


def test_a_descendant_alive_before_the_phase_adds_no_cpu_to_it() -> None:
    start = snapshot(descendants={9: 10})

    assert time_limit.phase_cpu(start, snapshot(descendants={9: 60})) == 0


@pytest.mark.parametrize(
    ("now", "seconds"),
    [
        (snapshot(process=105, tasks={7: 100}, descendants={9: 10}, reaped=1), 4),
        (snapshot(process=104, tasks={7: 100, 8: 3}, descendants={9: 10}, reaped=1), 3),
        (snapshot(process=104, tasks={7: 100}, descendants={9: 10}, reaped=1), 3),
        (snapshot(process=101, tasks={7: 100}, descendants={9: 10, 10: 2}, reaped=1), 2),
        (snapshot(process=101, tasks={7: 100}, descendants={9: 10}, reaped=6.5), 5.5),
    ],
    ids=[
        "main thread",
        "new task",
        "thread that started and ended in the phase",
        "new descendant",
        "reaped children",
    ],
)
def test_a_phase_counts_the_process_what_children_started_and_what_children_gave(
    now: CpuSnapshot, seconds: float
) -> None:
    start = snapshot(process=101, tasks={7: 100}, descendants={9: 10}, reaped=1)

    assert time_limit.phase_cpu(start, now) == pytest.approx(seconds)


def test_a_new_thread_of_the_plugins_own_adds_no_cpu_to_the_phase() -> None:
    start = snapshot(process=101, tasks={7: 100})
    now = snapshot(process=103, tasks={7: 100, 8: 2})

    assert time_limit.phase_cpu(start, now, own=[8]) == 0
    assert time_limit.phase_cpu(start, now) == pytest.approx(2)


def test_a_child_reaped_in_the_phase_is_billed_only_for_what_it_used_in_the_phase() -> None:
    start = snapshot(descendants={9: 10}, reaped=1, children=frozenset({9}))
    now = snapshot(reaped=13)

    assert time_limit.phase_cpu(start, now) == pytest.approx(2)
    assert time_limit.phase_cpu(snapshot(descendants={9: 10}, reaped=1), now) == pytest.approx(12)


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


# --- the phase trace (spec: test-failure-evidence) ---------------------------------------
#
# `PhaseTrace` is driven over fake snapshots, a fake clock, a fixed load and a pressure folder
# of the test's own; its file is read back as JSON lines.


class Clock:
    """A monotonic clock a test moves by hand."""

    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _trace(
    tmp_path: Path, clock: Clock, *, path: Path | None = None, pressure: str = "none"
) -> tuple[PhaseTrace, Path]:
    """A trace writing to `trace.jsonl` in `tmp_path` (or `path`), a load of 1.5 and a pressure
    folder `pressure` in `tmp_path` that does not exist unless a test makes it."""
    target = tmp_path / "trace.jsonl" if path is None else path
    return PhaseTrace(
        target, clock=clock, load=lambda: (1.5, 1.0, 0.5), pressure_dir=tmp_path / pressure
    ), target


def _lines(path: Path) -> list[dict]:
    assert path.exists(), f"no trace file at {path}"
    return [json.loads(line) for line in path.read_text().splitlines()]


def _end_phase(trace: PhaseTrace, clock: Clock, nodeid: str, *, seconds: float = 1.0) -> None:
    """A phase of `nodeid` that takes `seconds` of the fake clock and 0.5 s of CPU."""
    began = clock.now
    clock.now += seconds
    trace.phase_ended(
        nodeid, "call", started=began, start=snapshot(process=10), now=snapshot(process=10.5)
    )


def test_a_passing_phase_adds_one_entry_and_writes_nothing(tmp_path: Path) -> None:
    clock = Clock()
    trace, path = _trace(tmp_path, clock)
    start = snapshot(process=10, tasks={7: 1, 8: 1})
    now = snapshot(
        process=10.4, tasks={7: 1.2, 8: 1.1}, descendants={9: 0.2}, children=frozenset({9})
    )

    trace.phase_ended("a.py::test_x", "setup", started=98.0, start=start, now=now)

    (entry,) = trace.entries
    assert (entry.test, entry.phase) == ("a.py::test_x", "setup")
    assert entry.wall == pytest.approx(2.0)
    assert entry.cpu == pytest.approx(0.4)
    assert (entry.threads, entry.children, entry.load) == (3, 1, 1.5)
    assert not path.exists()


def test_the_trace_keeps_the_last_two_hundred_entries(tmp_path: Path) -> None:
    clock = Clock()
    trace, _ = _trace(tmp_path, clock)
    assert time_limit.TRACE_KEPT == 200

    for number in range(250):
        _end_phase(trace, clock, f"a.py::test_{number}")

    assert len(trace.entries) == 200
    assert trace.entries[0].test == "a.py::test_50"
    assert trace.entries[-1].test == "a.py::test_249"


def test_a_phase_over_five_seconds_of_wall_time_is_written_with_its_wall_and_cpu_seconds(
    tmp_path: Path,
) -> None:
    clock = Clock()
    trace, path = _trace(tmp_path, clock)

    _end_phase(trace, clock, "a.py::test_slow", seconds=7.5)

    (line,) = _lines(path)
    assert line["kind"] == "slow"
    assert line["test"] == "a.py::test_slow"
    assert line["phase"] == "call"
    assert line["wall"] == pytest.approx(7.5)
    assert line["cpu"] == pytest.approx(0.5)


def test_a_phase_under_five_seconds_is_not_written_beside_a_slow_one(tmp_path: Path) -> None:
    clock = Clock()
    trace, path = _trace(tmp_path, clock)

    _end_phase(trace, clock, "a.py::test_quick", seconds=4.9)
    _end_phase(trace, clock, "a.py::test_slow", seconds=5.1)

    assert [line["test"] for line in _lines(path)] == ["a.py::test_slow"]


def _trip(trace: PhaseTrace) -> None:
    """A trip of a phase billed 68 s: 69 s of process growth, 3 s of it an inherited thread's
    and 2 s the plugin's own, and a child of 4 s that the phase started."""
    trace.tripped(
        "a.py::test_x",
        "setup",
        clock="cpu",
        start=snapshot(process=101, tasks={7: 100}, reaped=1),
        now=snapshot(
            process=170,
            tasks={7: 103, 8: 2},
            descendants={9: 4},
            reaped=1,
            children=frozenset({9}),
        ),
        own=[8],
        left_by={7: ("thread poller", "b.py::test_earlier")},
    )


def test_a_trip_writes_each_term_of_the_billed_cpu(tmp_path: Path) -> None:
    trace, path = _trace(tmp_path, Clock())

    _trip(trace)

    (line,) = _lines(path)
    assert line["kind"] == "trip"
    assert (line["test"], line["phase"], line["clock"]) == ("a.py::test_x", "setup", "cpu")
    assert line["terms"] == pytest.approx(
        {"process": 69, "inherited": 3, "own": 2, "new_children": 4, "reaped": 0, "total": 68}
    )


def test_a_trip_names_the_thread_and_the_child_with_their_seconds(tmp_path: Path) -> None:
    trace, path = _trace(tmp_path, Clock())

    _trip(trace)

    (line,) = _lines(path)
    (thread,) = line["threads"]
    assert thread["name"] == "thread poller"
    assert thread["left_by"] == "b.py::test_earlier"
    assert thread["seconds"] == pytest.approx(3)
    (child,) = line["children"]
    assert child["pid"] == 9
    assert child["seconds"] == pytest.approx(4)


def test_a_trip_writes_the_load(tmp_path: Path) -> None:
    trace, path = _trace(tmp_path, Clock())

    _trip(trace)

    assert _lines(path)[0]["load"] == [1.5, 1.0, 0.5]


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({}, {"cpu": "unavailable", "io": "unavailable"}),
        ({"cpu": "some avg10=1.00\n"}, {"cpu": "some avg10=1.00\n", "io": "unavailable"}),
        (
            {"cpu": "some avg10=1.00\n", "io": "some avg10=2.00\n"},
            {"cpu": "some avg10=1.00\n", "io": "some avg10=2.00\n"},
        ),
    ],
    ids=["no pressure files", "cpu only", "both"],
)
def test_a_trip_writes_the_pressure_readings_or_unavailable(
    tmp_path: Path, files: dict[str, str], expected: dict[str, str]
) -> None:
    if files:
        (tmp_path / "pressure").mkdir()
        for name, text in files.items():
            (tmp_path / "pressure" / name).write_text(text)
    trace, path = _trace(tmp_path, Clock(), pressure="pressure")

    _trip(trace)

    assert _lines(path)[0]["pressure"] == expected


def test_a_trip_writes_the_last_thirty_entries_of_the_trace(tmp_path: Path) -> None:
    clock = Clock()
    trace, path = _trace(tmp_path, clock)
    for number in range(40):
        _end_phase(trace, clock, f"a.py::test_{number}")
    assert time_limit.TRIP_ENTRIES == 30

    _trip(trace)

    recent = _lines(path)[0]["recent"]
    assert [entry["test"] for entry in recent] == [f"a.py::test_{n}" for n in range(10, 40)]
    assert {"phase", "wall", "cpu", "threads", "children", "load"} <= set(recent[0])


def _raise(message: str) -> BaseException:
    try:
        raise AssertionError(message)
    except AssertionError as error:
        return error


def test_the_setups_after_a_trip_keep_their_full_traceback_for_two_errors_only(
    tmp_path: Path,
) -> None:
    trace, path = _trace(tmp_path, Clock())
    _trip(trace)

    for number in range(3):
        trace.error_raised(f"a.py::test_{number}", "setup", _raise(f"boom {number}"))

    tracebacks = [line for line in _lines(path) if line["kind"] == "traceback"]
    assert [line["test"] for line in tracebacks] == ["a.py::test_0", "a.py::test_1"]
    assert "Traceback (most recent call last)" in tracebacks[0]["traceback"]
    assert "_raise" in tracebacks[0]["traceback"], "the frame the error was raised in"
    assert "boom 1" in tracebacks[1]["traceback"]


def test_an_error_before_any_trip_is_not_written(tmp_path: Path) -> None:
    trace, path = _trace(tmp_path, Clock())

    trace.error_raised("a.py::test_0", "setup", _raise("boom"))

    assert not path.exists()


def test_a_trace_without_a_file_keeps_its_entries_and_writes_nothing(tmp_path: Path) -> None:
    clock = Clock()
    trace = PhaseTrace(None, clock=clock, load=lambda: (0.0, 0.0, 0.0), pressure_dir=tmp_path)

    _end_phase(trace, clock, "a.py::test_slow", seconds=9)
    _trip(trace)
    trace.error_raised("a.py::test_0", "setup", _raise("boom"))

    assert len(trace.entries) == 1
    assert list(tmp_path.iterdir()) == []


def test_a_trace_file_that_cannot_be_written_is_dropped_without_failing(tmp_path: Path) -> None:
    (tmp_path / "in-the-way").write_text("a file where the folder should be")
    clock = Clock()
    trace, path = _trace(tmp_path, clock, path=tmp_path / "in-the-way" / "trace.jsonl")

    _end_phase(trace, clock, "a.py::test_slow", seconds=9)
    _trip(trace)
    trace.error_raised("a.py::test_0", "setup", _raise("boom"))

    assert not path.exists()
    assert len(trace.entries) == 1


def test_a_trip_writes_a_trace_line_to_the_file_the_variable_names(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "trace.jsonl"

    result = run_scenario(
        pytester,
        CPU_SCENARIO,
        "hangs.py",
        "--test-time-limit=1",
        env={time_limit.TRACE_VARIABLE: str(path)},
        monkeypatch=monkeypatch,
    )

    assert result.code == 1, result.output
    trips = [line for line in _lines(path) if line["kind"] == "trip"]
    assert [trip["test"] for trip in trips] == ["hangs.py::test_hangs"]
    assert trips[0]["phase"] == "call"


def test_a_trip_without_the_variable_writes_no_file_and_fails_the_same_way(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(time_limit.TRACE_VARIABLE, raising=False)
    traced = tmp_path / "traced" / "trace.jsonl"
    with_variable = run_scenario(
        pytester,
        CPU_SCENARIO,
        "hangs.py",
        "--test-time-limit=1",
        env={time_limit.TRACE_VARIABLE: str(traced)},
        monkeypatch=monkeypatch,
    )
    assert traced.exists(), "the control run writes its trace"

    result = run_scenario(
        pytester, CPU_SCENARIO, "hangs.py", "--test-time-limit=1", monkeypatch=monkeypatch
    )

    assert result.code == with_variable.code == 1, result.output
    assert "1 failed, 1 passed" in result.output
    assert "exceeded the CPU time budget of 1 s" in result.output, result.output
    assert list(pytester.path.rglob("*.jsonl")) == []
