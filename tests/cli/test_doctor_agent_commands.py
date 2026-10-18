"""`abk doctor` reports the commands a build agent is told it may run (spec:
toolchain-profiles, build-prompts)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit import profiles, skills
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import EnvironmentConfig, RepoConfig, WorkspaceConfig, dump
from agent_build_kit.init.scaffold import render_openspec_config
from tests.agent_command_fakes import Outside, Silent, command
from tests.factories import init_repo, which_all


def ok_run(argv, **kwargs):
    if argv[0] == "git":
        return subprocess.run(argv, **kwargs)
    if argv[0] == "npx":
        return subprocess.CompletedProcess(argv, 0, "1.0.0\n", "")
    if argv[0] == "gh":
        return subprocess.CompletedProcess(argv, 0, "tok\n", "")
    return subprocess.CompletedProcess(argv, 0, "", "")


def planning_with(tmp_path: Path, **fields: object) -> Path:
    root = init_repo(tmp_path / "planning")
    app = init_repo(tmp_path / "app")
    (app / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n")
    (app / ".gitattributes").write_text("CHANGELOG.md merge=union\n")
    environment = EnvironmentConfig(sync=["env-sync"], check=["env-check"])
    config = WorkspaceConfig(
        environment=environment,
        repos={
            "app": RepoConfig(
                path=app,
                slug="example/app",
                environment=environment,
                **fields,  # type: ignore[arg-type]
            )
        },
    )
    (root / "abk.yaml").write_text(dump(config))
    (root / "openspec").mkdir()
    (root / "openspec" / "config.yaml").write_text(render_openspec_config(config))
    skills.install(root / ".claude" / "skills")
    return root


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
    assert "1 commands, all allowed" in check.detail or "1 command, all allowed" in check.detail


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
