"""`abk doctor` reports the commands a build agent is told it may run (spec:
toolchain-profiles, build-prompts)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import (
    ProjectConfig,
)
from tests.agent_command_fakes import Outside, Silent, command
from tests.doctor_fakes import ok_run, planning_with
from tests.factories import which_all


def agent_checks(planning: Path) -> list[Check]:
    checks = run_doctor(planning / "abk.yaml", run=ok_run, which=which_all)
    return [c for c in checks if c.name == "agent commands app"]


def test_a_repo_with_commands_gets_an_ok_line_with_their_number(tmp_path: Path) -> None:
    [check] = agent_checks(planning_with(tmp_path))

    assert check.status == "ok"
    assert "4 commands, all allowed" in check.detail


def test_a_repo_with_no_commands_gets_an_info_line(tmp_path: Path) -> None:
    with profiles.registered(Silent()):
        [check] = agent_checks(planning_with(tmp_path, profile="fake-silent"))

    assert check.status == "info"


def test_an_override_replaces_the_count(tmp_path: Path) -> None:
    [check] = agent_checks(
        planning_with(tmp_path, agent_commands=[command("test", "uv run pytest -q")])
    )

    assert check.status == "ok"
    assert "1 command, all allowed" in check.detail


def test_a_profile_command_outside_its_allowed_tools_fails_naming_it_and_the_fix(
    tmp_path: Path,
) -> None:
    with profiles.registered(Outside()):
        [check] = agent_checks(planning_with(tmp_path, profile="fake-outside"))

    assert check.status == "FAIL"
    assert "fake-outside" in check.detail
    assert "ruff check ." in check.detail
    assert "allow it in the profile" in check.fix
    assert "repos.app.agent_commands" in check.fix


def test_commands_that_would_not_all_fit_the_prompt_section_warn(tmp_path: Path) -> None:
    long = [command("test", f"uv run tool-{n:02d} --option-with-a-long-name") for n in range(20)]

    [check] = agent_checks(planning_with(tmp_path, agent_commands=long))

    assert check.status == "warn"
    assert "600" in f"{check.detail} {check.fix}"


def test_a_command_of_a_projects_profile_outside_the_list_names_the_repos_profiles(
    tmp_path: Path,
) -> None:
    with profiles.registered(Outside()):
        planning = planning_with(
            tmp_path, projects=[ProjectConfig(path="svc", profile="fake-outside")]
        )
        [check] = agent_checks(planning)

    assert check.status == "FAIL"
    assert "profiles of repo app" in check.detail
    assert "fake-outside" in check.detail
