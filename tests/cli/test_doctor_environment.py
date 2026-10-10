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
from tests.factories import git, init_repo

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


def environment(*, artifacts: list[str] | None = None, **inputs: list[str]) -> EnvironmentConfig:
    return EnvironmentConfig(
        sync=["env-sync"],
        check=CHECK,
        inputs=EnvironmentInputs(**inputs),
        artifacts=artifacts or [],
    )


def doctor(
    tmp_path: Path,
    *,
    planning_environment: EnvironmentConfig | None = None,
    repo_environment: EnvironmentConfig | None = None,
    run: Answers | None = None,
    files: tuple[str, ...] = (),
    tracked_in_app: tuple[str, ...] = (),
) -> list[Check]:
    planning = init_repo(tmp_path / "planning")
    app = init_repo(tmp_path / "app")
    for name in files:
        (planning / name).parent.mkdir(parents=True, exist_ok=True)
        (planning / name).write_text("")
    for name in tracked_in_app:
        (app / name).parent.mkdir(parents=True, exist_ok=True)
        (app / name).write_text("committed\n")
    if tracked_in_app:
        git(app, "add", "-A")
        git(app, "commit", "-qm", "tracked")
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


def test_sections_everywhere_raise_no_warning_even_for_a_pattern_in_a_subfolder(
    tmp_path: Path,
) -> None:
    checks = doctor(
        tmp_path,
        planning_environment=environment(dependencies=["**/manifest.toml"]),
        repo_environment=environment(),
        files=("packages/api/manifest.toml",),
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


def test_a_check_whose_executable_is_missing_is_a_failure_not_a_crash(tmp_path: Path) -> None:
    class Missing(CheckAnswers):
        def __call__(self, argv, **kwargs):
            if list(argv) == CHECK:
                raise FileNotFoundError(2, "No such file or directory", argv[0])
            return super().__call__(argv, **kwargs)

    checks = doctor(
        tmp_path,
        planning_environment=environment(),
        repo_environment=environment(),
        run=Missing(),
    )

    failed = [c for c in about_environment(checks) if c.status == "FAIL"]
    assert len(failed) == 1
    assert " ".join(CHECK) in failed[0].detail
    assert any("rules" in c.name for c in checks), "the checks after it still ran"


def test_a_pattern_that_matches_a_file_is_not_reported_missing(tmp_path: Path) -> None:
    checks = doctor(
        tmp_path,
        planning_environment=environment(dependencies=["**/manifest.toml"], lock=["manifest.lock"]),
        repo_environment=environment(),
        files=("packages/api/manifest.toml", "manifest.lock"),
    )

    assert not [c for c in about_environment(checks) if c.status in ("warn", "FAIL")]


def test_a_pattern_that_matches_nothing_is_reported_by_its_text(tmp_path: Path) -> None:
    checks = doctor(
        tmp_path,
        planning_environment=environment(
            dependencies=["**/manifest.toml", "**/gone.toml"], lock=["manifest.lock"]
        ),
        repo_environment=environment(),
        files=("packages/api/manifest.toml", "manifest.lock"),
    )

    found = [c for c in about_environment(checks) if c.status in ("warn", "FAIL")]
    assert len(found) == 1
    assert "**/gone.toml" in f"{found[0].name} {found[0].detail}"
    assert "**/manifest.toml" not in found[0].detail


def test_a_pattern_matching_nothing_in_a_repository_is_reported_naming_it(tmp_path: Path) -> None:
    checks = doctor(
        tmp_path,
        planning_environment=environment(),
        repo_environment=environment(dependencies=["**/manifest.toml"]),
    )

    found = [c for c in about_environment(checks) if c.status in ("warn", "FAIL")]
    assert len(found) == 1
    assert "app" in found[0].name
    assert "**/manifest.toml" in found[0].detail


def test_an_artifact_pattern_over_a_tracked_file_is_warned_about_naming_the_pattern(
    tmp_path: Path,
) -> None:
    checks = doctor(
        tmp_path,
        planning_environment=environment(),
        repo_environment=environment(artifacts=["vendor", "modules"]),
        tracked_in_app=("vendor/lib/code.txt", "src/code.txt"),
    )

    found = [c for c in about_environment(checks) if c.status == "warn"]
    assert len(found) == 1
    words = f"{found[0].name} {found[0].detail}"
    assert "vendor" in words and "app" in words
    assert "modules" not in words, "a pattern covering nothing tracked is fine"
    assert "tracked" in words


def test_an_artifact_pattern_with_nothing_tracked_under_it_raises_no_warning(
    tmp_path: Path,
) -> None:
    checks = doctor(
        tmp_path,
        planning_environment=environment(),
        repo_environment=environment(artifacts=["modules", "**/build"]),
        tracked_in_app=("src/code.txt",),
    )

    found = about_environment(checks)
    assert {c.status for c in found} <= {"ok", "info"}
