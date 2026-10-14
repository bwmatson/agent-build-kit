"""A flake keeps the failing test's own section of the first run's output, and a storm keeps
the first three (spec: flake-failure).

The profile reads the recorded pytest output under `tests/fixtures/external/pytest/`; tier 1
runs over a fake runner that answers with such output (see `test_flake_isolation`).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

import pytest

from agent_build_kit.pipeline.flakes import Flake, FlakeFound, flake_record
from agent_build_kit.pipeline.wiring import build_tier1
from agent_build_kit.profiles.base import ToolchainProfile
from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.conftest import make_installation
from tests.pipeline.test_flake_isolation import (
    FAILED,
    RECORDED,
    HookedProfile,
    Runs,
    recorded_failure,
)
from tests.pipeline.test_flake_storm import storms
from tests.redaction_fakes import NAME, SECRET, known
from tests.storm_fakes import ManyFailed

FAILURES = "=" * 35 + " FAILURES " + "=" * 35
SUMMARY = "=" * 12 + " short test summary info " + "=" * 12


def section(name: str, body: str) -> str:
    return f"{'_' * 20} {name} {'_' * 20}\n\n{body}\n"


class FirstRun(Runs):
    """`Runs`, with `output` as the first run's text instead of the recorded one."""

    def __init__(self, output: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.output = output

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if command != ["lint"] and not any("::" in argument for argument in command):
            self.commands.append(command)
            return subprocess.CompletedProcess(command, self.run_exit, self.output, "")
        return super().__call__(command, **kwargs)


class WithoutSections(HookedProfile):
    """`HookedProfile` whose profile offers no `failure_sections` hook."""

    def __getattribute__(self, name: str):
        if name == "failure_sections":
            raise AttributeError(name)
        return super().__getattribute__(name)


def storm_lines(number: int) -> list[str]:
    return [f"case {number:03} line {n:03} " + "y" * 30 for n in range(100)]


def storm_section(number: int) -> str:
    return "\n".join(storm_lines(number))


class StormSections(ManyFailed):
    """`ManyFailed`, each of the 97 tests with a section of 5000 characters."""

    def failure_sections(self, output: str) -> dict[str, str]:
        return {f"test_one.py::test_case_{n:03}": storm_section(n) for n in range(97)}


def tier1(
    profile: object, runs: Runs, tmp_path: Path, log: list[str] | None = None
) -> tuple[bool, str]:
    return build_tier1(
        profile=cast(ToolchainProfile, profile),
        run=runs,
        changed=lambda *a: ["tests/test_one.py"],
        log=log.append if log is not None else None,
    )(cwd=tmp_path, base="main")


def flakes_of(profile: object, runs: Runs, tmp_path: Path) -> dict[str, Flake]:
    with pytest.raises(FlakeFound) as found:
        tier1(profile, runs, tmp_path)
    return {flake.test: flake for flake in found.value.flakes}


# --- the profile's hook ----------------------------------------------------------


def test_each_failed_test_has_its_own_block_and_no_other_tests_text() -> None:
    sections = PythonUvProfile().failure_sections(recorded_failure())

    plain = sections["test_one.py::test_plain"]
    method = sections["test_one.py::TestGroup::test_method"]
    case = sections["test_one.py::test_cases[2]"]
    other = sections["test_two.py::test_other"]
    assert "assert 1 == 2" in plain
    assert "AssertionError: assert 'a' == 'b'" in method
    assert "assert 2 == 1" in case
    assert "assert [] == [1]" in other
    assert "assert 'a' == 'b'" not in plain and "assert 2 == 1" not in plain
    assert "assert 1 == 2" not in method and "assert 2 == 1" not in method
    assert "assert 'a' == 'b'" not in case and "assert [] == [1]" not in case
    assert "assert 2 == 1" not in other, "the block ends at the next header"
    assert "short test summary info" not in other, "the block ends where the summary starts"
    assert set(sections) <= set(FAILED)


def long_titles() -> str:
    return (RECORDED / "console_long_titles.txt").read_text().split("\n", 1)[1]


LONG_TITLED = [
    "test_long.py::test_noisy",
    "test_long.py::TestAVeryLongGroupName::test_a_long_name_that_pytest_cannot_pad",
    "test_params.py::test_a_parametrised_name_long_enough_that_the_title_is_padded_once"
    "[a-long-parameter-value-for-the-title]",
]


def test_a_title_padded_with_one_underscore_still_starts_its_own_block() -> None:
    sections = PythonUvProfile().failure_sections(long_titles())

    noisy, grouped, padded = (sections[test] for test in LONG_TITLED)
    assert "AssertionError: assert 'a' == 'b'" in grouped
    assert "AssertionError: assert 'a' == 'b'" not in noisy
    assert "assert 'a-long-parameter-value-for-the-title' == 1" in padded
    assert "assert 'a-long-parameter-value-for-the-title' == 1" not in grouped


def test_a_line_that_looks_like_a_rule_in_captured_output_does_not_end_the_failures() -> None:
    sections = PythonUvProfile().failure_sections(long_titles())

    assert "=== step ===" in sections[LONG_TITLED[0]], "the noisy test's own output is kept"
    assert set(sections) == set(LONG_TITLED), "the tests after it still have their sections"


def test_a_run_with_no_failures_section_has_no_sections() -> None:
    assert PythonUvProfile().failure_sections("3 passed in 0.01s\n") == {}


# --- the flake --------------------------------------------------------------------


def test_a_flake_carries_its_own_section_and_not_the_whole_output(tmp_path: Path) -> None:
    flakes = flakes_of(HookedProfile(), Runs(reruns=[0, 0]), tmp_path)

    plain = flakes["test_one.py::test_plain"].failure
    assert "assert 1 == 2" in plain
    assert "assert 'a' == 'b'" not in plain and "short test summary info" not in plain
    assert "assert 'a' == 'b'" in flakes["test_one.py::TestGroup::test_method"].failure
    assert "assert 2 == 1" in flakes["test_one.py::test_cases[2]"].failure
    assert "short test summary info" in flakes["test_one.py::test_plain"].output, "output stays"


def test_a_test_with_no_block_has_an_empty_failure(tmp_path: Path) -> None:
    output = (
        f"{FAILURES}\n{section('test_a', 'E   assert 1 == 2')}{SUMMARY}\n"
        "FAILED test_one.py::test_a - assert 1 == 2\n"
        "FAILED test_one.py::test_missing - boom\n2 failed in 0.01s\n"
    )

    flakes = flakes_of(HookedProfile(), FirstRun(output, reruns=[0, 0]), tmp_path)

    assert "assert 1 == 2" in flakes["test_one.py::test_a"].failure
    assert flakes["test_one.py::test_missing"].failure == ""


def test_the_section_is_redacted(tmp_path: Path) -> None:
    output = (
        f"{FAILURES}\n{section('test_a', f'E   token={SECRET} refused')}{SUMMARY}\n"
        "FAILED test_one.py::test_a - refused\n1 failed in 0.01s\n"
    )

    with known():
        flakes = flakes_of(HookedProfile(), FirstRun(output, reruns=[0, 0]), tmp_path)

    failure = flakes["test_one.py::test_a"].failure
    assert f"[redacted:{NAME}]" in failure
    assert SECRET not in failure


def test_a_long_section_is_kept_from_its_end_in_whole_lines_within_6000_characters(
    tmp_path: Path,
) -> None:
    filler = "".join(f"captured line {n:04} " + "x" * 30 + "\n" for n in range(400))
    body = f"begins here\n{filler}E   the real error\n\ntest_one.py:3: AssertionError"
    output = (
        f"{FAILURES}\n{section('test_a', body)}{SUMMARY}\n"
        "FAILED test_one.py::test_a - the real error\n1 failed in 0.01s\n"
    )

    flakes = flakes_of(HookedProfile(), FirstRun(output, reruns=[0, 0]), tmp_path)

    failure = flakes["test_one.py::test_a"].failure
    assert 5900 < len(failure) <= 6000
    assert failure.rstrip().endswith("test_one.py:3: AssertionError")
    assert "begins here" not in failure
    assert failure in output
    assert failure.splitlines()[0].startswith("captured line"), "the cut falls between lines"


PRINTED = [f"console line {n:05d} of a long output" for n in range(600)]


def long_run() -> str:
    return "\n".join(PRINTED) + "\n" + recorded_failure()


def test_a_flake_keeps_the_end_of_the_first_runs_output_in_whole_lines(tmp_path: Path) -> None:
    flakes = flakes_of(HookedProfile(), FirstRun(long_run(), reruns=[0, 0]), tmp_path)

    kept = flakes["test_one.py::test_plain"].output
    original = long_run().splitlines()
    assert 3000 < len(kept) <= 4000
    assert kept.splitlines()[-1] == original[-1], "the end of the output is kept"
    assert set(kept.splitlines()) <= set(original), "no line starts or ends in the middle"


def test_a_failed_command_keeps_the_end_of_what_it_printed_in_whole_lines(tmp_path: Path) -> None:
    passed, text = tier1(HookedProfile(), FirstRun(long_run(), reruns=[0, 1]), tmp_path)

    assert not passed
    original = long_run().splitlines()
    lines = text.splitlines()
    assert lines[0].startswith("$ "), "the header names the command"
    assert len(text) <= 4000 + 400, "the tail is cut to 4000 beside a short header"
    assert lines[-1] == original[-1], "the end of the output is kept"
    assert set(lines[2:]) <= set(original), "no line starts or ends in the middle"


def test_a_profile_without_the_hook_gives_the_same_flake_with_an_empty_failure(
    tmp_path: Path,
) -> None:
    with_hook = flakes_of(HookedProfile(), Runs(reruns=[0, 0]), tmp_path)
    without = flakes_of(WithoutSections(), Runs(reruns=[0, 0]), tmp_path)

    assert with_hook["test_one.py::test_plain"].failure != ""
    assert list(without) == list(with_hook)
    for test, flake in without.items():
        assert flake.failure == ""
        assert flake.model_dump(exclude={"at", "failure"}) == with_hook[test].model_dump(
            exclude={"at", "failure"}
        )


# --- the storm --------------------------------------------------------------------


def test_ninety_seven_flakes_record_and_log_three_sections_cut_to_3000(tmp_path: Path) -> None:
    installation = make_installation(tmp_path)
    logged: list[str] = []

    passed, _ = tier1(StormSections(), Runs(reruns=[0, 0]), tmp_path, logged)

    assert passed
    (storm,) = storms(installation)
    failures = storm["failures"]
    assert len(failures) == 3
    for n, failure in enumerate(failures):
        lines = storm_lines(n)
        assert 2900 < len(failure) <= 3000
        assert failure.splitlines()[-1] == lines[-1], "the end of the section is kept"
        assert set(failure.splitlines()) <= set(lines), "every line is whole"
    text = "\n".join(logged)
    for failure in failures:
        assert failure in text
    assert storm_lines(3)[-1] not in text, "only the first three"
    assert flake_record(installation).entries() == [], "no per-test record"
