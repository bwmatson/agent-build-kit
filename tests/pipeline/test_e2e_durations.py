"""An e2e-test result records the time of every phase of every test (spec:
e2e-time-is-recorded-per-test).

The profile reads pytest's `slowest durations` section; the gate merges what each
project's command printed, labelled with the project and slowest first. The runner is
injected at the process boundary and answers with what pytest prints.
"""

import subprocess
from pathlib import Path

from agent_build_kit.config import ProjectConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.e2e import TestTime, build_snapshot
from agent_build_kit.profiles import node_npm
from agent_build_kit.profiles.python_uv import PROFILE as PYTHON_UV
from tests.e2e_duration_fakes import (
    E2E,
    durations_output,
    recorded_times,
    run_e2e,
    sixteen_tests,
    time_line,
)
from tests.e2e_failure_fakes import NO_SUMMARY, NODE_OUTPUT, checkout, gate, run_returning
from tests.redaction_fakes import NAME, SECRET, known

NINE_MINUTES = 540.0
FOURTEEN_MINUTES = 840.0


def test_a_setup_and_a_call_of_one_test_are_two_entries() -> None:
    output = durations_output(
        (FOURTEEN_MINUTES, "call", f"{E2E}::test_a"),
        (NINE_MINUTES, "setup", f"{E2E}::test_a"),
        (1.5, "teardown", f"{E2E}::test_a"),
    )

    assert PYTHON_UV.parse_test_durations(output) == [
        TestTime(test=f"{E2E}::test_a", phase="call", seconds=FOURTEEN_MINUTES),
        TestTime(test=f"{E2E}::test_a", phase="setup", seconds=NINE_MINUTES),
        TestTime(test=f"{E2E}::test_a", phase="teardown", seconds=1.5),
    ]


def test_sixteen_tests_give_sixteen_entries_in_the_order_printed() -> None:
    entries = sixteen_tests()

    found = PYTHON_UV.parse_test_durations(durations_output(*entries))

    assert [(t.test, t.phase, t.seconds) for t in found] == [
        (test, phase, seconds) for seconds, phase, test in entries
    ]


def test_the_note_of_hidden_durations_is_not_an_entry() -> None:
    output = durations_output((3.0, "call", f"{E2E}::test_a"), hidden=7)

    found = PYTHON_UV.parse_test_durations(output)

    assert [t.test for t in found] == [f"{E2E}::test_a"]


def test_an_id_with_a_space_in_its_parameters_is_kept_whole() -> None:
    test = f"{E2E}::test_param[a b]"

    found = PYTHON_UV.parse_test_durations(durations_output((2.0, "call", test)))

    assert [t.test for t in found] == [test]


def test_a_durations_section_quoted_in_captured_output_is_not_the_runs_own() -> None:
    inner = f"{E2E}::test_inner"
    captured = (
        "----------------------------- Captured stdout call -----------------------------",
        "=" * 29 + " slowest durations " + "=" * 29,
        f"4.00s call     {inner}",
        "-" * 80,
    )
    output = durations_output((9.0, "call", f"{E2E}::test_outer"), before=captured)

    assert [t.test for t in PYTHON_UV.parse_test_durations(output)] == [f"{E2E}::test_outer"]
    kept = PYTHON_UV.without_durations(output)
    assert all(line in kept for line in captured)
    assert "test_outer" not in kept
    assert kept.count("slowest durations") == 1


def test_an_output_with_no_durations_section_gives_no_entries() -> None:
    assert PYTHON_UV.parse_test_durations(NO_SUMMARY) == []
    assert PYTHON_UV.parse_test_durations("") == []


def test_a_node_runner_output_gives_no_entries() -> None:
    assert node_npm.PROFILE.parse_test_durations(NODE_OUTPUT) == []


def _answering(by_project: dict[str, str]):
    """A runner whose answer is the output named for the directory it runs in."""

    def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(command, 0, by_project[Path(kwargs["cwd"]).name], "")

    return run


def test_two_projects_entries_are_merged_labelled_and_slowest_first(tmp_path: Path) -> None:
    root = checkout(tmp_path, "api", "web")
    session = gate(
        tmp_path,
        _answering(
            {
                "api": durations_output(
                    (30.0, "call", f"{E2E}::test_a"), (200.0, "setup", "t.py::x")
                ),
                "web": durations_output((FOURTEEN_MINUTES, "call", f"{E2E}::test_b")),
            }
        ),
        projects=[ProjectConfig(path="api"), ProjectConfig(path="web")],
    )

    ok, _ = session.run(cwd=root)

    assert ok
    assert session.result is not None
    assert [(t.test, t.phase, t.seconds) for t in session.result.durations] == [
        (f"web/{E2E}::test_b", "call", FOURTEEN_MINUTES),
        ("api/t.py::x", "setup", 200.0),
        (f"api/{E2E}::test_a", "call", 30.0),
    ]


def test_the_result_is_otherwise_as_without_durations(tmp_path: Path) -> None:
    root = checkout(tmp_path, "api")
    with_durations = gate(
        tmp_path,
        _answering({"api": durations_output((9.0, "call", f"{E2E}::test_a"))}),
        projects=[ProjectConfig(path="api")],
    )
    plain = gate(
        tmp_path,
        _answering({"api": "1 passed in 9.00s"}),
        projects=[ProjectConfig(path="api")],
    )

    with_durations.run(cwd=root)
    plain.run(cwd=root)

    assert with_durations.result is not None and plain.result is not None
    assert with_durations.result.durations
    assert plain.result.durations == []
    for field in ("passed", "failed", "skipped", "command"):
        assert getattr(with_durations.result, field) == getattr(plain.result, field)


def test_a_test_id_is_redacted_in_the_result_the_listing_and_the_ledger(
    tmp_path: Path, workspace: Installation
) -> None:
    test = f"{E2E}::test_auth[{SECRET}]"
    split = time_line(test, "call", checks_ms=1000)
    output = durations_output((30.0, "call", test), lines=(split,))

    with known():
        result = run_e2e(tmp_path, output)
    snapshot = build_snapshot(result)

    masked = f"{E2E}::test_auth[[redacted:{NAME}]]"
    assert [e.test for e in result.durations] == [masked]
    assert result.durations[0].checks_ms == 1000
    assert masked in snapshot
    assert [row["test"] for row in recorded_times(workspace)] == [masked]
    assert SECRET not in snapshot
    assert SECRET not in repr(result.durations)
    assert SECRET not in str(recorded_times(workspace))


def _forty() -> list[tuple[float, str, str]]:
    return [(90.0 - n, "call", f"{E2E}::test_{n:02d}") for n in range(40)]


def _entry_lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if "s call " in line and "::test_" in line]


def test_the_kept_output_of_a_failing_command_leaves_out_the_durations_section(
    tmp_path: Path,
) -> None:
    traceback = (
        "=================================== FAILURES ===================================",
        "_________________________________ test_00 ______________________________",
        f"{E2E}:9: in test_00",
        "    assert 1 == 2",
        "E   assert 1 == 2",
    )
    summary = (
        "=========================== short test summary info ============================",
        f"FAILED {E2E}::test_00 - assert 1 == 2",
    )
    output = durations_output(*_forty(), before=traceback, after=summary)
    root = checkout(tmp_path)
    session = gate(tmp_path, run_returning(output, code=1))

    ok, snapshot = session.run(cwd=root)

    assert not ok
    assert session.result is not None
    assert "E   assert 1 == 2" in session.result.output
    assert _entry_lines(session.result.output) == []
    assert "slowest durations" not in session.result.output
    assert len(session.result.durations) == 40
    assert "15 of 40 shown" in snapshot.split("<details>")[0]


def test_the_kept_output_of_a_passing_command_leaves_out_the_durations_section(
    tmp_path: Path,
) -> None:
    root = checkout(tmp_path)
    session = gate(tmp_path, run_returning(durations_output(*_forty()), code=0))

    session.run(cwd=root)

    assert session.result is not None
    assert "passed in" in session.result.output
    assert _entry_lines(session.result.output) == []
