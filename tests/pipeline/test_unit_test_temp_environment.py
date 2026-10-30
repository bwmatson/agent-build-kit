"""The unit-test step gives every command it runs the profile's test environment, when the
profile has one (spec: test-temp-folders-clean-up)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, cast

from agent_build_kit import profiles
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.wiring import build_unit_test
from agent_build_kit.profiles.base import ToolchainProfile

VARIABLE = "PYTEST_DEBUG_TEMPROOT"


class EnvRecorder:
    """A runner that records each command and the `env` it was given (None for none)."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.envs: list[dict[str, str] | None] = []

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        self.commands.append(args)
        self.envs.append(kwargs.get("env"))
        return subprocess.CompletedProcess(args, 0, "", "")


class WithoutTestEnvironment:
    """The python-uv profile as a profile that lacks the optional member."""

    def __init__(self) -> None:
        self._profile = profiles.get("python-uv")

    def __getattr__(self, name: str) -> Any:
        if name == "test_environment":
            raise AttributeError(name)
        return getattr(self._profile, name)


def repo_with_a_test(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    return repo


def run_unit_test(
    repo: Path, installation: Installation, profile: ToolchainProfile | None = None
) -> EnvRecorder:
    recorder = EnvRecorder()
    build_unit_test(
        run=recorder,
        changed=lambda *a: ["tests/test_x.py"],
        profile=profile,
        installation=installation,
    )(cwd=repo, base="main")
    return recorder


def test_each_command_gets_a_temp_root_under_the_installations_pytest_temp_root(
    tmp_path: Path, installation: Installation
) -> None:
    recorder = run_unit_test(repo_with_a_test(tmp_path), installation)

    assert recorder.commands
    assert all(env is not None for env in recorder.envs)
    roots = {Path(env[VARIABLE]) for env in recorder.envs if env}
    assert len(roots) == 1
    (root,) = roots
    assert root.parent == installation.pytest_temp_root
    assert root.is_dir()


def test_the_environment_keeps_what_the_process_has(
    tmp_path: Path, installation: Installation
) -> None:
    recorder = run_unit_test(repo_with_a_test(tmp_path), installation)

    assert all(env and env["PATH"] == os.environ["PATH"] for env in recorder.envs)


def test_a_profile_without_the_member_leaves_the_commands_environment_alone(
    tmp_path: Path, installation: Installation
) -> None:
    recorder = run_unit_test(
        repo_with_a_test(tmp_path),
        installation,
        profile=cast(ToolchainProfile, WithoutTestEnvironment()),
    )

    assert recorder.commands
    assert recorder.envs == [None] * len(recorder.commands)
    assert not installation.pytest_temp_root.exists()


def test_no_installation_means_no_environment(tmp_path: Path) -> None:
    recorder = EnvRecorder()
    build_unit_test(run=recorder, changed=lambda *a: ["tests/test_x.py"])(
        cwd=repo_with_a_test(tmp_path), base="main"
    )

    assert recorder.envs == [None] * len(recorder.commands)
