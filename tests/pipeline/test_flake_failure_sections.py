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
from tests.pipeline.test_flake_isolation import FAILED, HookedProfile, Runs, recorded_failure
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


def storm_section(number: int) -> str:
    return f"case {number:03} " + "y" * 4980 + f" ends {number:03}"


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


def test_a_long_section_is_kept_from_its_end_to_6000_characters(tmp_path: Path) -> None:
    body = "begins here\n" + "x" * 20000 + "\nE   the real error\n\ntest_one.py:3: AssertionError"
    output = (
        f"{FAILURES}\n{section('test_a', body)}{SUMMARY}\n"
        "FAILED test_one.py::test_a - the real error\n1 failed in 0.01s\n"
    )

    flakes = flakes_of(HookedProfile(), FirstRun(output, reruns=[0, 0]), tmp_path)

    failure = flakes["test_one.py::test_a"].failure
    assert len(failure) == 6000
    assert failure.rstrip().endswith("test_one.py:3: AssertionError")
    assert "begins here" not in failure
    assert failure in output


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
    expected = [storm_section(n)[-3000:] for n in range(3)]
    assert storm["failures"] == expected
    text = "\n".join(logged)
    for failure in expected:
        assert failure in text
    assert storm_section(3)[-3000:] not in text, "only the first three"
    assert flake_record(installation).entries() == [], "no per-test record"
