"""`abk doctor` decides a configured repo is a checkout by its working-tree root, like the track
runner and `abk init`: a stray `.git` folder that is not a repository is not one."""

from __future__ import annotations

import shutil
from pathlib import Path

from agent_build_kit.cli.doctor import run_doctor
from tests.doctor_fakes import ok_run, planning_with
from tests.factories import which_all


def test_a_repo_with_a_stray_git_folder_fails_as_not_a_checkout(tmp_path: Path) -> None:
    planning = planning_with(tmp_path)
    shutil.rmtree(tmp_path / "app" / ".git")
    (tmp_path / "app" / ".git").mkdir()

    checks = run_doctor(planning / "abk.yaml", run=ok_run, which=which_all)

    repo = next(c for c in checks if c.name == "repo app")
    assert repo.status == "FAIL"
    assert "is not a git checkout" in repo.detail
