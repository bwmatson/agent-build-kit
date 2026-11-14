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
    [("assertion_only", "a.test.ts"), ("not_implemented", "b.test.ts")],
    ids=["an assertion failure", "calling a stub"],
)
def test_a_test_failing_by_assertion_or_by_not_implemented_is_red(
    profile, project: Project, recording: str, file: str
) -> None:
    ok, problems = judge(profile, project, recording, [file])

    assert ok, problems
    assert problems == []


@pytest.mark.parametrize(
    ("recording", "file", "reason"),
    [
        ("missing_import", "c.test.ts", "could not be loaded"),
        ("syntax_error", "f.test.ts", "could not be loaded"),
        ("passing", "d.test.ts", "passed"),
        ("empty", "a.test.ts", "nothing failed"),
        ("other_not_implemented", "i.test.ts", "not one we recognise"),
    ],
    ids=[
        "an unresolved import",
        "a syntax error",
        "a passing test",
        "an empty run",
        "an error that only mentions not implemented",
    ],
)
def test_a_file_that_did_not_load_a_passing_test_or_an_empty_run_is_rejected_with_a_reason(
    profile, project: Project, recording: str, file: str, reason: str
) -> None:
    ok, problems = judge(profile, project, recording, [file])

    assert not ok
    assert any(reason in problem for problem in problems), problems


def test_a_test_failing_with_a_plain_error_is_red(profile, project: Project) -> None:
    ok, problems = judge(profile, project, "plain_error", ["j.test.ts"])

    assert ok, problems
    assert problems == []


def test_a_test_failing_with_a_plain_error_is_red_in_the_stubbed_reading_too(
    profile, project: Project
) -> None:
    done = project.run(profile.red_command(["j.test.ts"]), recording="plain_error")

    ok, problems = profile.interpret_red(done.stdout + done.stderr, done.returncode, stubbed=True)

    assert ok, problems


@pytest.mark.parametrize(
    ("recording", "file", "error_type"),
    [
        ("type_error_thrown", "k.test.ts", "TypeError"),
        ("reference_error_thrown", "l.test.ts", "ReferenceError"),
        ("syntax_error_thrown", "m.test.ts", "SyntaxError"),
    ],
    ids=["a type error", "a reference error", "a syntax error in the test body"],
)
def test_a_test_failing_with_a_missing_name_or_a_broken_test_is_rejected_naming_the_type(
    profile, project: Project, recording: str, file: str, error_type: str
) -> None:
    ok, problems = judge(profile, project, recording, [file])

    assert not ok
    assert any(error_type in problem for problem in problems), problems


def test_a_plain_error_failure_beside_a_passing_test_is_rejected_for_the_passing_test(
    profile, project: Project
) -> None:
    ok, problems = judge(profile, project, "error_and_passing", ["n.test.ts"])

    assert not ok
    assert any("passed" in problem for problem in problems), problems
    assert not any("recognise" in problem for problem in problems), problems


@pytest.mark.parametrize(
    ("recording", "file"),
    [("missing_import", "c.test.ts"), ("syntax_error", "f.test.ts")],
    ids=["an unresolved import", "a syntax error"],
)
def test_a_test_file_that_did_not_load_is_named_with_the_start_of_its_error(
    profile, project: Project, recording: str, file: str
) -> None:
    done = project.run(profile.red_command([file]), recording=recording)

    found = profile.collection_errors(done.stdout + done.stderr)

    assert found[0] == f"could not load {file}:"
    assert len(found) > 1


def test_a_run_whose_files_all_loaded_reports_no_collection_error(
    profile, project: Project
) -> None:
    done = project.run(profile.red_command(["a.test.ts"]), recording="assertion_only")

    assert profile.collection_errors(done.stdout + done.stderr) == []


def test_a_given_file_with_no_failing_test_is_named_when_another_given_file_is_red(
    profile, project: Project
) -> None:
    """Every given file has to be red, not only one of them."""
    ok, problems = judge(profile, project, "assertion_only", ["a.test.ts", "z.test.ts"])

    assert not ok
    assert any("z.test.ts" in problem and "nothing failed" in problem for problem in problems)


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
