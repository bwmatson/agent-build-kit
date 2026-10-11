"""The tests a unit adds or changed are run again, under load, after tier 1 passes
(spec: flaky-tests).

The checkout is a real git repository, since which tests the unit touched is read from its
history. The command runner is the faked boundary: it answers each command with an exit
status and output, and the repeat runs are the commands that name a touched test.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

from agent_build_kit.config import LimitsConfig
from agent_build_kit.pipeline.wiring import build_tier1
from agent_build_kit.profiles.base import ToolchainProfile
from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.conftest import make_installation
from tests.factories import git, init_repo

RUN = ["uv", "run", "pytest", "-n", "auto", "-q"]
LINT = ["lint"]

UNTOUCHED = "def test_untouched():\n    assert 1 == 1\n"
WEAKENED_BEFORE = "def test_weakened():\n    assert 1 == 1\n"
WEAKENED_AFTER = "def test_weakened():\n    assert True\n"
ADDED = "def test_added():\n    assert 2 == 2\n"
FAILURE = "1 failed: test_added  assert 2 == 3"


class Profile(PythonUvProfile):
    """The python-uv profile running one lint command and one parallel test command."""

    def lint_command(self, base: str) -> list[str]:
        return LINT

    def test_commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str]
    ) -> list[list[str]]:
        return [RUN]


class Runs:
    """Answers lint and the full run with a pass; any other command is a repeat run, which
    exits as `repeats` says, one entry per run, passing once they run out."""

    def __init__(self, repeats: list[int] | None = None) -> None:
        self.repeats = list(repeats or [])
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.commands.append(command)
        if command in (LINT, RUN):
            return subprocess.CompletedProcess(command, 0, "12 passed\n", "")
        exit_code = self.repeats.pop(0) if self.repeats else 0
        output = "1 passed\n" if exit_code == 0 else FAILURE + "\n"
        return subprocess.CompletedProcess(command, exit_code, output, "")

    @property
    def repeat_runs(self) -> list[list[str]]:
        return [c for c in self.commands if c not in (LINT, RUN)]

    def repeating(self, test: str) -> list[list[str]]:
        return [c for c in self.repeat_runs if test in " ".join(c)]


def checkout(tmp_path: Path, files: dict[str, str]) -> tuple[Path, str]:
    """A repo whose base holds `test_untouched` and `test_weakened`, and a unit's commit
    that writes `files` over it. Returns the repo and the base."""
    repo = init_repo(tmp_path / "repo")
    (repo / "test_old.py").write_text(UNTOUCHED + "\n\n" + WEAKENED_BEFORE)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD").strip()
    for name, text in files.items():
        (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "unit", "--allow-empty")
    return repo, base


def tier1(runs: Runs, repo: Path, base: str, **limits: int) -> tuple[bool, str]:
    make_installation(repo.parent / "planning", limits=limits)
    return build_tier1(
        profile=cast(ToolchainProfile, Profile()), run=runs, changed=lambda *a: ["test_new.py"]
    )(cwd=repo, base=base)


def test_the_setting_defaults_to_three_runs() -> None:
    assert LimitsConfig().tier1_repeat_runs == 3


def test_an_added_test_is_run_three_times_after_tier_1_passes(tmp_path: Path) -> None:
    repo, base = checkout(tmp_path, {"test_new.py": ADDED})
    runs = Runs()

    passed, message = tier1(runs, repo, base)

    assert (passed, message) == (True, "")
    assert len(runs.repeating("test_added")) == 3
    assert runs.commands[:2] == [LINT, RUN], "the check follows the ordinary run"
    assert runs.commands[2:] == runs.repeat_runs


def test_a_repeat_run_keeps_the_parallel_load_of_the_run_it_repeats(tmp_path: Path) -> None:
    repo, base = checkout(tmp_path, {"test_new.py": ADDED})
    runs = Runs()

    tier1(runs, repo, base)

    assert runs.repeat_runs
    for command in runs.repeat_runs:
        assert command[:5] == ["uv", "run", "pytest", "-n", "auto"]


def test_a_failure_in_any_repeat_run_fails_tier_1_with_that_run_s_output(
    tmp_path: Path,
) -> None:
    for failing in range(3):
        repo, base = checkout(tmp_path / str(failing), {"test_new.py": ADDED})
        repeats = [0, 0, 0]
        repeats[failing] = 1

        passed, message = tier1(Runs(repeats), repo, base)

        assert not passed, f"run {failing + 1} failed"
        assert FAILURE in message


def test_a_weakened_test_is_run_again_and_one_the_unit_did_not_touch_is_not(
    tmp_path: Path,
) -> None:
    repo, base = checkout(tmp_path, {"test_old.py": UNTOUCHED + "\n\n" + WEAKENED_AFTER})
    runs = Runs()

    tier1(runs, repo, base)

    assert len(runs.repeating("test_weakened")) == 3
    assert runs.repeating("test_untouched") == []


def test_only_the_touched_tests_are_named_in_the_repeat_runs(tmp_path: Path) -> None:
    repo, base = checkout(tmp_path, {"test_new.py": ADDED})
    runs = Runs()

    tier1(runs, repo, base)

    assert runs.repeat_runs
    for command in runs.repeat_runs:
        assert "test_untouched" not in " ".join(command)
        assert "test_weakened" not in " ".join(command)


def test_the_number_of_runs_is_the_setting(tmp_path: Path) -> None:
    repo, base = checkout(tmp_path, {"test_new.py": ADDED})
    runs = Runs()

    tier1(runs, repo, base, tier1_repeat_runs=5)

    assert len(runs.repeating("test_added")) == 5
