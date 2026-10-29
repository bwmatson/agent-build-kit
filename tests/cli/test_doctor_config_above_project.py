"""`abk doctor` looks for the pre-commit configuration from a registered project's folder up to
the checkout root, and names the file it found."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import ProjectConfig
from tests.cli.test_doctor_python_tools import HOOKS_FILE, PINNED_HOOK, pyproject
from tests.doctor_fakes import ok_run, planning_with
from tests.factories import which_all


def ruff_warning(tmp_path: Path, *, config_in: str) -> Check | None:
    """Doctor on a repo whose project `svc` pins ruff in its group and whose hook file is in
    `config_in` (`.` for the checkout root); the warning about ruff, if any."""
    planning = planning_with(tmp_path, projects=[ProjectConfig(path="svc")])
    project = tmp_path / "app" / "svc"
    project.mkdir()
    (project / "pyproject.toml").write_text(pyproject("ruff==0.16.8"))
    (tmp_path / "app" / config_in / HOOKS_FILE).write_text(PINNED_HOOK)
    checks = run_doctor(planning / "abk.yaml", run=ok_run, which=which_all)
    return next((c for c in checks if c.status == "warn" and "ruff" in c.name), None)


def test_a_configuration_at_the_root_is_found_for_a_project(tmp_path: Path) -> None:
    found = ruff_warning(tmp_path, config_in=".")

    assert found is not None
    assert HOOKS_FILE in found.detail


def test_a_configuration_in_the_project_folder_is_found_and_named(tmp_path: Path) -> None:
    found = ruff_warning(tmp_path, config_in="svc")

    assert found is not None
    assert f"svc/{HOOKS_FILE}" in found.detail
