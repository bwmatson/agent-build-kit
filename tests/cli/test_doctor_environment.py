"""`abk doctor` and the `environment` section: it warns where none is managed,
reports a listed input that is missing, and runs `check`."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import (
    EnvironmentConfig,
    EnvironmentInputs,
    RepoConfig,
    WorkspaceConfig,
    dump,
)
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo

CHECK = ["env-check", "--quiet"]


class CheckAnswers(Answers):
    """Git and gh as before; the environment's `check` answers with a chosen
    exit status and output."""

    def __init__(self, *, status: int = 0, output: str = "") -> None:
        super().__init__()
        self.status = status
        self.output = output

    def __call__(self, argv, **kwargs):
        if list(argv) == CHECK:
            self.commands.append(list(argv))
            return subprocess.CompletedProcess(argv, self.status, self.output, "")
        return super().__call__(argv, **kwargs)


def environment(**inputs: list[str]) -> EnvironmentConfig:
    return EnvironmentConfig(sync=["env-sync"], check=CHECK, inputs=EnvironmentInputs(**inputs))


def doctor(
    tmp_path: Path,
    *,
    planning_environment: EnvironmentConfig | None = None,
    repo_environment: EnvironmentConfig | None = None,
    run: Answers | None = None,
    files: tuple[str, ...] = (),
) -> list[Check]:
    planning = init_repo(tmp_path / "planning")
    app = init_repo(tmp_path / "app")
    for name in files:
        (planning / name).write_text("")
    config = WorkspaceConfig(
        environment=planning_environment,
        repos={
            "app": RepoConfig(
                path=app, slug="example/app", changelog=None, environment=repo_environment
            )
        },
    )
    (planning / "abk.yaml").write_text(dump(config))
    return run_doctor(planning / "abk.yaml", run=run or CheckAnswers(), which=which_all)


def about_environment(checks: list[Check]) -> list[Check]:
    return [c for c in checks if "environment" in c.name.lower()]


def test_no_section_is_warned_about_as_managing_nothing_and_runs_no_check(
    tmp_path: Path,
) -> None:
    run = CheckAnswers()

    checks = doctor(tmp_path, repo_environment=environment(), run=run)

    found = [c for c in about_environment(checks) if c.status == "warn"]
    assert len(found) == 1
    assert "app" not in found[0].name
    assert "none" in found[0].detail.lower() or "no environment" in found[0].detail.lower()
    assert CHECK not in run.commands


def test_a_repository_without_a_section_is_warned_about_naming_it(tmp_path: Path) -> None:
    checks = doctor(tmp_path, planning_environment=environment())

    found = [c for c in about_environment(checks) if c.status == "warn"]
    assert len(found) == 1
    assert "app" in f"{found[0].name} {found[0].detail}"


def test_sections_everywhere_raise_no_warning_even_for_an_input_outside_the_repo(
    tmp_path: Path,
) -> None:
    (tmp_path / "framework").mkdir()
    (tmp_path / "framework" / "manifest.toml").write_text("")

    checks = doctor(
        tmp_path,
        planning_environment=environment(dependencies=["../framework/manifest.toml"]),
        repo_environment=environment(),
    )

    found = about_environment(checks)
    assert found, "the environment is reported on even when it is fine"
    assert {c.status for c in found} <= {"ok", "info"}


def test_a_listed_input_that_does_not_exist_is_reported(tmp_path: Path) -> None:
    checks = doctor(
        tmp_path,
        planning_environment=environment(
            dependencies=["manifest.toml", "gone.toml"], lock=["manifest.lock"]
        ),
        repo_environment=environment(),
        files=("manifest.toml", "manifest.lock"),
    )

    found = [c for c in about_environment(checks) if c.status in ("warn", "FAIL")]
    assert len(found) == 1
    assert "gone.toml" in f"{found[0].name} {found[0].detail}"
    assert "manifest.toml" not in found[0].detail.replace("gone.toml", "")


def test_doctor_runs_the_check_and_reports_a_pass(tmp_path: Path) -> None:
    run = CheckAnswers()

    checks = doctor(
        tmp_path, planning_environment=environment(), repo_environment=environment(), run=run
    )

    assert CHECK in run.commands
    assert any(c.status == "ok" for c in about_environment(checks))


def test_doctor_reports_a_failing_check_with_its_output(tmp_path: Path) -> None:
    run = CheckAnswers(status=3, output="ModuleNotFoundError: no module named widget\n")

    checks = doctor(
        tmp_path, planning_environment=environment(), repo_environment=environment(), run=run
    )

    found = [c for c in about_environment(checks) if c.status in ("warn", "FAIL")]
    assert len(found) == 1
    assert "ModuleNotFoundError" in found[0].detail
