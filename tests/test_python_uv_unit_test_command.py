"""The unit-test command prints the slowest tests and a short summary of what failed
(spec: test-failure-evidence)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.profiles.python_uv import PythonUvProfile

FLAGS = ["--durations=15", "--durations-min=3.0", "-rfE"]
XDIST = '[project]\nname = "app"\nversion = "0"\ndependencies = ["pytest-xdist"]\n'


def _repo(tmp_path: Path, manifest: str) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(manifest)
    return tmp_path


@pytest.mark.parametrize(
    ("manifest", "passes"),
    [('[project]\nname = "app"\nversion = "0"\n', 1), (XDIST, 2)],
    ids=["serial only", "parallel then serial"],
)
def test_every_pass_of_the_repos_tests_carries_the_durations_flags(
    tmp_path: Path, manifest: str, passes: int
) -> None:
    repo = _repo(tmp_path, manifest)

    commands = PythonUvProfile().test_commands(repo, ["tests/test_x.py"], root_extras=[])

    assert len(commands) == passes
    for command in commands:
        assert all(flag in command for flag in FLAGS), command


def test_the_whole_repo_commands_carry_them_too(tmp_path: Path) -> None:
    repo = _repo(tmp_path, XDIST)

    for command in PythonUvProfile().test_commands_all(repo, root_extras=[]):
        assert all(flag in command for flag in FLAGS), command
