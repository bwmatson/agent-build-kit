"""Red is judged by why a test failed (spec: node-npm-red-and-stubs).

Each case runs the profile's red command for real in a project whose `npx` writes a
recording of the report Vitest wrote (`tests/fixtures/external/vitest/`), and judges the
output and exit status that come back, as the gate does.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import profiles
from tests.node_npx_fake import Project, make_project


@pytest.fixture
def profile():
    return profiles.get("node-npm")


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return make_project(tmp_path)


def judge(profile, project: Project, recording: str, files: list[str]) -> tuple[bool, list[str]]:
    done = project.run(profile.red_command(files), recording=recording)
    return profile.interpret_red(done.stdout + done.stderr, done.returncode)


@pytest.mark.parametrize(
    ("recording", "file"),
    [("assertion", "a.test.ts"), ("not_implemented", "b.test.ts")],
    ids=["an assertion failure", "calling a stub"],
)
def test_a_test_failing_by_assertion_or_by_not_implemented_is_red(
    profile, project: Project, recording: str, file: str
) -> None:
    ok, problems = judge(profile, project, recording, [file])

    assert ok, problems
    assert problems == []


@pytest.mark.parametrize(
    ("recording", "file"),
    [
        ("missing_import", "c.test.ts"),
        ("syntax_error", "f.test.ts"),
        ("passing", "d.test.ts"),
        ("empty", "a.test.ts"),
    ],
    ids=["an unresolved import", "a syntax error", "a passing test", "an empty run"],
)
def test_a_file_that_did_not_load_a_passing_test_or_an_empty_run_is_rejected_with_a_reason(
    profile, project: Project, recording: str, file: str
) -> None:
    ok, problems = judge(profile, project, recording, [file])

    assert not ok
    assert problems and all(problem.strip() for problem in problems)


def test_a_suite_from_a_file_that_was_not_given_is_ignored(profile, project: Project) -> None:
    """Vitest's filters match by substring, so a passing suite of another file may appear."""
    ok, problems = judge(profile, project, "extra_suite", ["g.test.ts"])

    assert ok, problems


def test_the_same_report_is_rejected_when_the_passing_suites_file_is_given(
    profile, project: Project
) -> None:
    ok, problems = judge(profile, project, "extra_suite", ["g.test.ts", "h.test.ts"])

    assert not ok
    assert problems


def test_a_report_with_only_suites_of_files_not_given_is_rejected(
    profile, project: Project
) -> None:
    """Nothing the gate asked for ran, so nothing is red."""
    ok, problems = judge(profile, project, "assertion", ["other.test.ts"])

    assert not ok
    assert problems
