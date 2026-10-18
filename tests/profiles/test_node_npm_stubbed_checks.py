"""node-npm reads a Vitest report of the red run in a stubbed mode (spec: test-stubs).

Each case runs the profile's red command for real in a project whose `npx` writes a
recording of the report Vitest wrote (`tests/fixtures/external/vitest/`).
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


def judge_stubbed(profile, project: Project, recording: str, file: str) -> tuple[bool, list[str]]:
    done = project.run(profile.red_command([file]), recording=recording)
    return profile.interpret_red(done.stdout + done.stderr, done.returncode, stubbed=True)


@pytest.mark.parametrize(
    ("recording", "file"),
    [("assertion_only", "a.test.ts"), ("not_implemented", "b.test.ts")],
    ids=["an assertion failure", "a not implemented error"],
)
def test_an_assertion_failure_or_a_not_implemented_error_is_red_when_stubbed(
    profile, project: Project, recording: str, file: str
) -> None:
    ok, problems = judge_stubbed(profile, project, recording, file)

    assert ok, problems


@pytest.mark.parametrize(
    ("recording", "file", "reason"),
    [
        ("missing_import", "c.test.ts", "could not be loaded"),
        ("passing", "d.test.ts", "passed"),
    ],
    ids=["a suite that failed to load", "a passing test"],
)
def test_a_suite_that_failed_to_load_and_a_passing_test_are_rejected_when_stubbed(
    profile, project: Project, recording: str, file: str, reason: str
) -> None:
    ok, problems = judge_stubbed(profile, project, recording, file)

    assert not ok
    assert any(reason in problem for problem in problems), problems
