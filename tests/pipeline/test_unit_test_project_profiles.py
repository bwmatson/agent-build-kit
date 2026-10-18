"""Unit-test judges each project by its own toolchain (spec: node-npm-lint-and-test).

A python repo with a project of another profile: the extra checks, the reading of a failure
and the tools a build run may use come from the profile of the project the work belongs to.
The command runner is the faked boundary; both project profiles are fakes, so no other
ecosystem's tooling is needed. A repo declaring no projects keeps what it had: its profile's
checks run once at the root, with no directory line, and they are read with its profile.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import forges, profiles
from agent_build_kit.config import ProjectConfig, RepoConfig
from agent_build_kit.pipeline.check_failures import failed_check
from agent_build_kit.pipeline.wiring import allowed_tools, build_unit_test
from tests.conftest import make_installation
from tests.project_profile_fakes import API, WEB, Api, Root, Web


@pytest.fixture(autouse=True)
def fake_profiles() -> Iterator[None]:
    with profiles.registered(Web()), profiles.registered(Api()), profiles.registered(Root()):
        yield


class Commands:
    """The faked runner: what ran, where, and how each word ends."""

    def __init__(self, **answers: tuple[int, str]) -> None:
        self.answers = answers
        self.ran: list[tuple[str, Path]] = []

    def __call__(self, command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        self.ran.append((command[0], cwd))
        code, out = self.answers.get(command[0], (0, ""))
        return subprocess.CompletedProcess(command, code, out, "")

    def words(self) -> list[str]:
        return [word for word, _ in self.ran]


def install_app(
    tmp_path: Path, projects: list[ProjectConfig] | None = None, profile: str = "python-uv"
) -> None:
    """The installation's repo `app`, of `profile`, holding `projects` (the web and api ones
    unless given)."""
    held = [WEB, API] if projects is None else projects
    app = RepoConfig(
        path=tmp_path / "app", slug="example/app", profile=profile, projects=held
    ).model_dump(mode="json")
    make_installation(tmp_path / "meta", repos={"app": app})


def unit_test(
    tmp_path: Path,
    commands: Commands,
    changed: list[str],
    projects: list[ProjectConfig] | None = None,
    profile: str = "python-uv",
) -> tuple[bool, str]:
    held = [WEB, API] if projects is None else projects
    for project in held:
        # A project whose directory is absent is pending, and nothing runs in it.
        (tmp_path / project.path).mkdir(parents=True, exist_ok=True)
    run = build_unit_test(
        run=commands,
        changed=lambda *a: changed,
        profile=profiles.get(profile),
        repo=RepoConfig(path=tmp_path, changelog=None, profile=profile, projects=held),
        projects=held,
    )
    return run(cwd=tmp_path, base="main")


def test_a_change_in_a_project_runs_that_projects_checks_in_its_directory(
    tmp_path: Path,
) -> None:
    commands = Commands()

    passed, _ = unit_test(tmp_path, commands, ["web/src/a.ts"])

    assert passed
    assert ("web-types", tmp_path / "web") in commands.ran
    assert "api-extra" not in commands.words()


def test_each_touched_project_runs_its_own_checks_in_its_own_directory(
    tmp_path: Path,
) -> None:
    commands = Commands()

    unit_test(tmp_path, commands, ["web/src/a.ts", "api/app.py"])

    assert ("web-types", tmp_path / "web") in commands.ran
    assert ("api-extra", tmp_path / "api") in commands.ran


def test_a_failed_project_check_is_classified_by_that_projects_profile(tmp_path: Path) -> None:
    install_app(tmp_path)
    commands = Commands(**{"web-types": (1, "error in a.ts")})

    passed, output = unit_test(tmp_path, commands, ["web/src/a.ts"])

    assert not passed
    assert failed_check(output, "app") == "types"


def test_a_failure_in_another_project_is_read_by_that_projects_profile(tmp_path: Path) -> None:
    install_app(tmp_path)
    commands = Commands(**{"api-extra": (1, "boom")})

    passed, output = unit_test(tmp_path, commands, ["api/app.py"])

    assert not passed
    assert failed_check(output, "app") == "test"


def test_the_allowed_tools_of_a_build_run_include_every_projects_profile() -> None:
    tools = allowed_tools(profiles.get("python-uv"), forges.get("github"), projects=[WEB, API])

    assert "Bash(webtool *)" in tools
    assert "Bash(apitool *)" in tools


def test_the_repo_profiles_checks_still_run_at_the_root_when_only_a_project_changed(
    tmp_path: Path,
) -> None:
    commands = Commands()

    unit_test(tmp_path, commands, ["web/src/a.ts", "CHANGELOG.md"], [WEB], "fake-root")

    assert commands.ran.count(("root-extra", tmp_path)) == 1
    assert ("web-types", tmp_path / "web") in commands.ran


def test_the_repo_profiles_checks_run_when_no_project_holds_the_change(tmp_path: Path) -> None:
    commands = Commands()

    unit_test(tmp_path, commands, ["CHANGELOG.md"], [WEB], "fake-root")

    assert ("root-extra", tmp_path) in commands.ran


def test_a_repo_without_projects_runs_its_profiles_checks_once_at_the_root(
    tmp_path: Path,
) -> None:
    commands = Commands()

    passed, _ = unit_test(tmp_path, commands, ["app.py"], [], "fake-root")

    assert passed
    assert commands.ran.count(("root-extra", tmp_path)) == 1


def test_a_repo_without_projects_reports_a_failed_check_without_a_directory_line(
    tmp_path: Path,
) -> None:
    install_app(tmp_path, [], "fake-root")
    commands = Commands(**{"root-extra": (1, "boom")})

    passed, output = unit_test(tmp_path, commands, ["app.py"], [], "fake-root")

    assert not passed
    assert "(in " not in output
    assert failed_check(output, "app") == "types"


def test_the_allowed_tools_without_projects_are_the_repo_profiles_alone() -> None:
    forge = forges.get("github")
    profile = profiles.get("fake-root")

    assert allowed_tools(profile, forge) == allowed_tools(profile, forge, projects=None)
    assert allowed_tools(profile, forge) == allowed_tools(profile, forge, projects=[])
    assert "Bash(roottool *)" in allowed_tools(profile, forge)


def test_a_directory_above_the_checkout_named_like_a_project_does_not_claim_the_failure(
    tmp_path: Path,
) -> None:
    install_app(tmp_path)
    output = "$ x (exit 1)\n(in /srv/web/wt/app/api)\nboom"

    assert failed_check(output, "app") == "test"


def test_a_project_using_the_repos_own_profile_is_checked_in_its_directory(
    tmp_path: Path,
) -> None:
    commands = Commands()

    unit_test(tmp_path, commands, ["web/src/a.ts"], [WEB], "fake-web")

    assert ("web-types", tmp_path / "web") in commands.ran
    assert ("web-types", tmp_path) not in commands.ran


def test_a_repo_without_projects_runs_its_project_checks_once_at_the_root(
    tmp_path: Path,
) -> None:
    install_app(tmp_path, [], "fake-web")
    commands = Commands(**{"web-types": (1, "error")})

    passed, output = unit_test(tmp_path, commands, ["a.ts"], [], "fake-web")

    assert not passed
    assert commands.ran.count(("web-types", tmp_path)) == 1
    assert failed_check(output, "app") == "types"


def test_a_checkout_wide_check_of_the_repo_profile_runs_at_the_root_only(
    tmp_path: Path,
) -> None:
    commands = Commands()
    svc = ProjectConfig(path="svc", profile="fake-root")

    unit_test(tmp_path, commands, ["svc/a.py"], [svc], "fake-root")

    assert [where for word, where in commands.ran if word == "root-extra"] == [tmp_path]


def test_a_failed_check_of_a_root_project_is_classified_by_that_projects_profile(
    tmp_path: Path,
) -> None:
    root_project = ProjectConfig(path=".", profile="fake-api")
    install_app(tmp_path, [root_project], "fake-root")
    commands = Commands(**{"api-extra": (1, "boom")})

    passed, output = unit_test(tmp_path, commands, ["src/a.py"], [root_project], "fake-root")

    assert not passed
    # The repo profile would say `types`; the root project's profile says `test`.
    assert failed_check(output, "app") == "test"


def test_a_project_absent_from_the_checkout_runs_none_of_its_checks(tmp_path: Path) -> None:
    commands = Commands()
    run = build_unit_test(
        run=commands,
        changed=lambda *a: ["web/src/a.ts"],
        profile=profiles.get("python-uv"),
        repo=RepoConfig(path=tmp_path, changelog=None, projects=[WEB]),
        projects=[WEB],
    )

    passed, _ = run(cwd=tmp_path, base="main")

    assert passed
    assert "web-types" not in commands.words()
