"""The built policy lets a unit-test step write the kit's pytest temp root and no other part of
the installation's `runs` folder (spec: test-temp-folders-clean-up)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import profiles
from tests.sandboxes.policy_support import Scene, writes


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return Scene(tmp_path)


def test_the_policy_for_a_python_repo_writes_a_run_folder_under_the_pytest_temp_root(
    scene: Scene,
) -> None:
    installation = scene.installation()
    policy = scene.policy(profile=profiles.get("python-uv"))

    run_folder = installation.pytest_temp_root / "add-marker-1-run1"
    run_folder.mkdir(parents=True)

    assert writes(policy, run_folder)
    assert writes(policy, run_folder / "pytest-of-user" / "pytest-0")


def test_the_policy_grants_no_other_part_of_runs(scene: Scene) -> None:
    installation = scene.installation()
    policy = scene.policy(profile=profiles.get("python-uv"))
    runs = installation.state_dir

    assert writes(policy, installation.pytest_temp_root / "add-marker-1-run1")
    assert not writes(policy, runs)
    assert not writes(policy, runs / "units.json")
    assert not writes(policy, runs / "tmp")
    assert not writes(policy, runs / "tmp" / "other")
    assert not writes(policy, runs / "logs")
