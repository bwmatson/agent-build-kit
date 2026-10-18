"""The tests a unit adds or changed are run again, under load, after unit-test passes
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
from agent_build_kit.pipeline.wiring import build_unit_test
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

    def _commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str]
    ) -> list[list[str]]:
        return [RUN]

    # Assigned, not defined: a scan for changed tests takes any `def test_*` for one.
    test_commands = _commands


class Runs:
    """Answers lint and the full run with a pass; any other command is a repeat run, which
    exits as `repeats` says, one entry per run, passing once they run out."""

    def __init__(
        self, repeats: list[int] | None = None, full: list[list[str]] | None = None
    ) -> None:
        self.repeats = list(repeats or [])
        self.full = full or [RUN]
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.commands.append(command)
        if command == LINT or command in self.full:
            return subprocess.CompletedProcess(command, 0, "12 passed\n", "")
        exit_code = self.repeats.pop(0) if self.repeats else 0
        output = "1 passed\n" if exit_code == 0 else FAILURE + "\n"
        return subprocess.CompletedProcess(command, exit_code, output, "")

    @property
    def repeat_runs(self) -> list[list[str]]:
        return [c for c in self.commands if c != LINT and c not in self.full]

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
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "unit", "--allow-empty")
    return repo, base


class NodeProfile(Profile):
    """A node-shaped profile: its tests run as `npm test`, a run that finds no tests exits 0,
    and its repeat command passes the identifiers after `--`."""

    no_tests_collected_exit = 0

    def _commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str]
    ) -> list[list[str]]:
        return [NPM_TEST]

    # Assigned, not defined: a scan for changed tests takes any `def test_*` for one.
    test_commands = _commands

    def repeat_command(self, command: list[str], tests: list[str]) -> list[str]:
        return [*command, "--", *tests]


MEMBERS = [
    ["uv", "run", "--package", "svc-a", "pytest", "svc-a", "-q"],
    ["uv", "run", "--package", "svc-b", "pytest", "svc-b", "-q"],
]


class WorkspaceProfile(Profile):
    """A workspace of two members, each with its own test command."""

    def _commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str]
    ) -> list[list[str]]:
        return MEMBERS

    # Assigned, not defined: a scan for changed tests takes any `def test_*` for one.
    test_commands = _commands


class WithoutRepeat:
    """`Profile` offering no `repeat_command`."""

    def __init__(self) -> None:
        self.inner = Profile()

    def __getattr__(self, name: str):
        if name == "repeat_command":
            raise AttributeError(name)
        return getattr(self.inner, name)


def unit_test(
    runs: Runs, repo: Path, base: str, profile: object | None = None, **limits: int
) -> tuple[bool, str]:
    make_installation(repo.parent / "planning", limits=limits)
    return build_unit_test(
        profile=cast(ToolchainProfile, profile or Profile()),
        run=runs,
        changed=lambda *a: ["test_new.py"],
    )(cwd=repo, base=base)


def test_the_setting_defaults_to_three_runs() -> None:
    assert LimitsConfig().unit_test_repeat_runs == 3


def test_an_added_test_is_run_three_times_after_unit_test_passes(tmp_path: Path) -> None:
    repo, base = checkout(tmp_path, {"test_new.py": ADDED})
    runs = Runs()

    passed, message = unit_test(runs, repo, base)

    assert (passed, message) == (True, "")
    assert len(runs.repeating("test_added")) == 3
    assert runs.commands[:2] == [LINT, RUN], "the check follows the ordinary run"
    assert runs.commands[2:] == runs.repeat_runs


def test_a_repeat_run_keeps_the_parallel_load_of_the_run_it_repeats(tmp_path: Path) -> None:
    repo, base = checkout(tmp_path, {"test_new.py": ADDED})
    runs = Runs()

    unit_test(runs, repo, base)

    assert runs.repeat_runs
    for command in runs.repeat_runs:
        assert command[:5] == ["uv", "run", "pytest", "-n", "auto"]


def test_a_failure_in_any_repeat_run_fails_unit_test_with_that_run_s_output(
    tmp_path: Path,
) -> None:
    for failing in range(3):
        repo, base = checkout(tmp_path / str(failing), {"test_new.py": ADDED})
        repeats = [0, 0, 0]
        repeats[failing] = 1

        passed, message = unit_test(Runs(repeats), repo, base)

        assert not passed, f"run {failing + 1} failed"
        assert FAILURE in message


def test_a_weakened_test_is_run_again_and_one_the_unit_did_not_touch_is_not(
    tmp_path: Path,
) -> None:
    repo, base = checkout(tmp_path, {"test_old.py": UNTOUCHED + "\n\n" + WEAKENED_AFTER})
    runs = Runs()

    unit_test(runs, repo, base)

    assert len(runs.repeating("test_weakened")) == 3
    assert runs.repeating("test_untouched") == []


def test_only_the_touched_tests_are_named_in_the_repeat_runs(tmp_path: Path) -> None:
    repo, base = checkout(tmp_path, {"test_new.py": ADDED})
    runs = Runs()

    unit_test(runs, repo, base)

    assert runs.repeat_runs
    for command in runs.repeat_runs:
        assert "test_untouched" not in " ".join(command)
        assert "test_weakened" not in " ".join(command)


def test_the_number_of_runs_is_the_setting(tmp_path: Path) -> None:
    repo, base = checkout(tmp_path, {"test_new.py": ADDED})
    runs = Runs()

    unit_test(runs, repo, base, unit_test_repeat_runs=5)

    assert len(runs.repeating("test_added")) == 5


def test_a_test_in_a_class_is_selected_by_its_class_path(tmp_path: Path) -> None:
    repo, base = checkout(tmp_path, {"test_new.py": METHOD})
    runs = Runs()

    unit_test(runs, repo, base)

    assert len(runs.repeat_runs) == 3
    for command in runs.repeat_runs:
        assert command[-1] == "test_new.py::TestGroup::test_method"


def test_a_repeat_run_selects_exact_identifiers_not_name_patterns(tmp_path: Path) -> None:
    repo, base = checkout(tmp_path, {"test_new.py": ADDED})
    runs = Runs()

    unit_test(runs, repo, base)

    assert runs.repeat_runs
    for command in runs.repeat_runs:
        assert command[-1] == "test_new.py::test_added"
        assert "-k" not in command


def test_a_profile_whose_nothing_collected_status_is_zero_still_repeats_every_run(
    tmp_path: Path,
) -> None:
    repo, base = checkout(tmp_path, {"test_new.py": ADDED})
    runs = Runs(full=[NPM_TEST])

    passed, _ = unit_test(runs, repo, base, NodeProfile())

    assert passed
    assert runs.repeat_runs == [[*NPM_TEST, "--", "test_new.py::test_added"]] * 3


def test_a_profile_without_a_repeat_command_runs_no_repeat(tmp_path: Path) -> None:
    repo, base = checkout(tmp_path, {"test_new.py": ADDED})
    runs = Runs()

    passed, message = unit_test(runs, repo, base, WithoutRepeat())

    assert (passed, message) == (True, "")
    assert runs.commands == [LINT, RUN]


def test_a_setting_of_zero_runs_no_repeat(tmp_path: Path) -> None:
    repo, base = checkout(tmp_path, {"test_new.py": ADDED})
    runs = Runs()

    passed, _ = unit_test(runs, repo, base, unit_test_repeat_runs=0)

    assert passed
    assert runs.commands == [LINT, RUN]


def test_a_base_that_cannot_be_resolved_skips_the_check_and_the_pass_stands(
    tmp_path: Path,
) -> None:
    repo, _ = checkout(tmp_path, {"test_new.py": ADDED})
    runs = Runs()

    passed, message = unit_test(runs, repo, "refs/does-not-exist")

    assert (passed, message) == (True, "")
    assert runs.commands == [LINT, RUN]


def test_a_test_of_one_member_is_repeated_only_by_that_member_s_command(tmp_path: Path) -> None:
    repo, base = checkout(tmp_path, {"svc-a/tests/test_x.py": ADDED})
    runs = Runs(full=MEMBERS)

    passed, _ = unit_test(runs, repo, base, WorkspaceProfile())

    assert passed
    assert (
        runs.repeat_runs
        == [
            ["uv", "run", "--package", "svc-a", "pytest", "-q", "svc-a/tests/test_x.py::test_added"]
        ]
        * 3
    )


def test_a_test_method_in_a_source_file_is_not_repeated(tmp_path: Path) -> None:
    source = "class Client:\n    def test_connection(self):\n        return True\n"
    repo, base = checkout(tmp_path, {"src/db.py": source, "test_new.py": ADDED})
    runs = Runs()

    passed, _ = unit_test(runs, repo, base)

    assert passed
    assert len(runs.repeat_runs) == 3
    for command in runs.repeat_runs:
        assert command[-1] == "test_new.py::test_added"
        assert "src/db.py" not in " ".join(command)
