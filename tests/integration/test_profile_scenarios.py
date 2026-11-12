"""The same six behaviours on a tiny fixture project per toolchain profile
(spec: profile-capability-parity).

Red by id, a passing new test rejected, a repeat by id, a serial rerun, failure parsing and
affected selection after a one-file change are asserted once, in the shared cases below, and run
over a Python project (real pytest through uv) and a node project (real Vitest through npx). The
projects differ only in the data of `tests/profile_scenario_projects.py`; a profile that cannot
do one of the six fails the case that names it. The tools are fetched on demand, so the cases
need the network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.profiles.base import (
    RecordsSelectionData,
    RepeatsTests,
    RerunsFailedTests,
    SelectsAffectedTests,
)
from tests.profile_scenario_projects import ScenarioProject

pytestmark = [pytest.mark.integration, pytest.mark.time_limit(300)]


@pytest.fixture(params=profiles.names())
def project(request: pytest.FixtureRequest, tmp_path: Path) -> ScenarioProject:
    return ScenarioProject(request.param, tmp_path / "tiny")


def test_a_new_failing_test_is_red_when_run_by_id(project: ScenarioProject) -> None:
    scenario = project.scenario
    project.write({scenario.new_path: scenario.new_failing})

    command = project.profile.red_command(
        [scenario.new_path], [scenario.new_id], project=project.root
    )
    done = project.run(command)
    accepted, problems = project.profile.interpret_red(done.output, done.returncode)

    assert done.returncode != 0, done.output
    assert (accepted, problems) == (True, []), done.output


def test_a_new_test_that_passes_is_rejected_as_red(project: ScenarioProject) -> None:
    scenario = project.scenario
    project.write({scenario.new_path: scenario.new_passing})

    command = project.profile.red_command(
        [scenario.new_path], [scenario.new_id], project=project.root
    )
    done = project.run(command)
    accepted, problems = project.profile.interpret_red(done.output, done.returncode)

    assert accepted is False, done.output
    assert problems, "the rejection gives its reason"


def test_a_repeat_by_id_runs_exactly_the_named_test(project: ScenarioProject) -> None:
    command, _ = project.full_run()
    profile = project.profile
    assert isinstance(profile, RepeatsTests)

    again = profile.repeat_command(command, [project.scenario.passing_id], project=project.root)
    assert again is not None
    done = project.run(again)

    assert done.returncode == 0, done.output
    assert project.counts(done.output) == (1, 0), done.output


def test_a_failed_run_names_its_failed_test_ids(project: ScenarioProject) -> None:
    broken = project.broken
    project.write({broken.path: broken.source})
    profile = project.profile

    _, done = project.full_run()

    assert done.returncode != 0, done.output
    assert isinstance(profile, RerunsFailedTests)
    assert profile.failed_tests(done.output) == [broken.test_id], done.output


def test_a_failed_test_reruns_serially_on_its_own(project: ScenarioProject) -> None:
    broken = project.broken
    project.write({broken.path: broken.source})
    command, _ = project.full_run()
    profile = project.profile
    assert isinstance(profile, RerunsFailedTests)
    assert isinstance(profile, RepeatsTests)

    rerun = profile.serial_rerun_command(command, [broken.test_id])
    done = project.run(rerun)

    assert rerun != command
    # Serial is what sets the rerun apart from an ordinary repeat of the same id.
    assert rerun != profile.repeat_command(command, [broken.test_id], project=project.root)
    assert done.returncode != 0, done.output
    assert project.counts(done.output) == (0, 1), done.output


def test_a_one_file_change_selects_only_the_tests_that_reach_it(project: ScenarioProject) -> None:
    profile = project.profile
    assert isinstance(profile, SelectsAffectedTests)
    if isinstance(profile, RecordsSelectionData):
        for command in profile.test_commands_all(project.root, root_extras=[]):
            seeding = profile.seeding_command(command, project.seed)
            recorded = project.run(seeding)
            assert profile.tolerates_exit(seeding, recorded.returncode), recorded.output
    scenario = project.scenario
    project.write({scenario.changed_file: scenario.changed_source})

    commands = profile.affected_test_commands(
        project.root, [scenario.changed_file], [], seed=project.seed, root_extras=[]
    )
    assert commands, "the profile can name the tests the change affects"
    runs = [project.run(command) for command in commands]

    # Only the test that reaches the changed file ran, and it fails on the change.
    assert sum(project.counts(r.output)[0] + project.counts(r.output)[1] for r in runs) == 1, [
        r.output for r in runs
    ]
    assert isinstance(profile, RerunsFailedTests)
    assert profile.failed_tests("\n".join(r.output for r in runs)) == [scenario.passing_id]
