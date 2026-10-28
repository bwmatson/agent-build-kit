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


# --- what a failing run's evidence says of its conditions --------------------------------

# What `pytest --version --version` printed, as recorded (tests/fixtures/external/record_pytest.py).
RECORDED = Path(__file__).resolve().parents[1] / "fixtures" / "external" / "pytest"
VERSIONS = (RECORDED / "version_verbose.txt").read_text()


def _parallel(tmp_path: Path) -> list[str]:
    return PythonUvProfile().test_commands(_repo(tmp_path, XDIST), ["x"], root_extras=[])[0]


def test_the_versions_are_asked_of_the_environment_the_command_runs_in(tmp_path: Path) -> None:
    command = _parallel(tmp_path)

    probe = PythonUvProfile().version_probe(command)

    assert probe == ["uv", "run", "pytest", "--version", "--version"]


def test_a_command_that_runs_no_pytest_has_no_probe() -> None:
    assert PythonUvProfile().version_probe(["make", "test"]) is None


def test_the_facts_are_read_from_the_probe_and_the_command_not_from_a_header(
    tmp_path: Path,
) -> None:
    """A `-q` run prints no header, so a header is not where the versions are."""
    facts = PythonUvProfile().run_facts(_parallel(tmp_path), VERSIONS)

    first, *plugins = VERSIONS.splitlines()
    recorded = first.removeprefix("This is pytest version ").split(",")[0]
    xdist = next(line.split()[0] for line in plugins if line.strip().startswith("pytest-xdist-"))
    versions = facts["versions"]
    assert isinstance(versions, dict)
    assert versions["pytest"] == recorded
    assert versions["pytest-xdist"] == xdist.removeprefix("pytest-xdist-"), "the dist's own name"
    assert "registered" not in versions, "only the plugin lines are read"


def test_a_setting_the_runner_resolves_is_not_guessed(tmp_path: Path) -> None:
    facts = PythonUvProfile().run_facts(_parallel(tmp_path), "")

    assert facts == {"workers_setting": "auto", "max_workers": 8}


def test_a_fixed_worker_count_is_recorded_as_given() -> None:
    facts = PythonUvProfile().run_facts(["uv", "run", "pytest", "-n", "4", "-q"], "")

    assert facts == {"workers_setting": "4", "workers": 4}


def test_a_serial_run_records_no_workers_and_a_silent_probe_no_versions() -> None:
    assert PythonUvProfile().run_facts(["uv", "run", "pytest", "-q"], "") == {}
