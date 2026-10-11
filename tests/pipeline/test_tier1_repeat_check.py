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
NPM_TEST = ["npm", "test"]
LINT = ["lint"]
METHOD = "class TestGroup:\n    def test_method(self):\n        assert 3 == 3\n"

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

    def __init__(self, repeats: list[int] | None = None, full: list[str] = RUN) -> None:
        self.repeats = list(repeats or [])
        self.full = full
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.commands.append(command)
        if command in (LINT, self.full):
            return subprocess.CompletedProcess(command, 0, "12 passed\n", "")
        exit_code = self.repeats.pop(0) if self.repeats else 0
        output = "1 passed\n" if exit_code == 0 else FAILURE + "\n"
        return subprocess.CompletedProcess(command, exit_code, output, "")

    @property
    def repeat_runs(self) -> list[list[str]]:
        return [c for c in self.commands if c not in (LINT, self.full)]

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


class NodeProfile(Profile):
    """A node-shaped profile: its tests run as `npm test`, a run that finds no tests exits 0,
    and its repeat command passes the identifiers after `--`."""

    no_tests_collected_exit = 0

    def test_commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str]
    ) -> list[list[str]]:
        return [NPM_TEST]

    def repeat_command(self, command: list[str], tests: list[str]) -> list[str]:
        return [*command, "--", *tests]


class WithoutRepeat:
    """`Profile` offering no `repeat_command`."""

    def __init__(self) -> None:
        self.inner = Profile()

    def __getattr__(self, name: str):
        if name == "repeat_command":
            raise AttributeError(name)
        return getattr(self.inner, name)


def tier1(
    runs: Runs, repo: Path, base: str, profile: object | None = None, **limits: int
) -> tuple[bool, str]:
    make_installation(repo.parent / "planning", limits=limits)
    return build_tier1(
        profile=cast(ToolchainProfile, profile or Profile()),
        run=runs,
        changed=lambda *a: ["test_new.py"],
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


def test_a_test_in_a_class_is_selected_by_its_class_path(tmp_path: Path) -> None:
    repo, base = checkout(tmp_path, {"test_new.py": METHOD})
    runs = Runs()

    tier1(runs, repo, base)

    assert len(runs.repeat_runs) == 3
    for command in runs.repeat_runs:
        assert command[-1] == "test_new.py::TestGroup::test_method"


def test_a_repeat_run_selects_exact_identifiers_not_name_patterns(tmp_path: Path) -> None:
    repo, base = checkout(tmp_path, {"test_new.py": ADDED})
    runs = Runs()

    tier1(runs, repo, base)

    assert runs.repeat_runs
    for command in runs.repeat_runs:
        assert command[-1] == "test_new.py::test_added"
        assert "-k" not in command


def test_a_profile_whose_nothing_collected_status_is_zero_still_repeats_every_run(
    tmp_path: Path,
) -> None:
    repo, base = checkout(tmp_path, {"test_new.py": ADDED})
    runs = Runs(full=NPM_TEST)

    passed, _ = tier1(runs, repo, base, NodeProfile())

    assert passed
    assert runs.repeat_runs == [[*NPM_TEST, "--", "test_new.py::test_added"]] * 3


def test_a_profile_without_a_repeat_command_runs_no_repeat(tmp_path: Path) -> None:
    repo, base = checkout(tmp_path, {"test_new.py": ADDED})
    runs = Runs()

    passed, message = tier1(runs, repo, base, WithoutRepeat())

    assert (passed, message) == (True, "")
    assert runs.commands == [LINT, RUN]


def test_a_setting_of_zero_runs_no_repeat(tmp_path: Path) -> None:
    repo, base = checkout(tmp_path, {"test_new.py": ADDED})
    runs = Runs()

    passed, _ = tier1(runs, repo, base, tier1_repeat_runs=0)

    assert passed
    assert runs.commands == [LINT, RUN]


def test_a_base_that_cannot_be_resolved_skips_the_check_and_the_pass_stands(
    tmp_path: Path,
) -> None:
    repo, _ = checkout(tmp_path, {"test_new.py": ADDED})
    runs = Runs()

    passed, message = tier1(runs, repo, "refs/does-not-exist")

    assert (passed, message) == (True, "")
    assert runs.commands == [LINT, RUN]
