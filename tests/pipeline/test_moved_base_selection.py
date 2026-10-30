"""What a scoped moved base runs, and when it runs the full suite instead (spec:
a-moved-base-is-checked-by-what-it-can-affect).

The repository is real: a unit's branch cut from a base, the base moved on, the branch
replayed on top of it. The command runner is faked at its boundary, answering each command
with an exit status and the summary line a test runner prints, except in the semantic
conflict, where a real pytest runs the selected test. The profile's commands are named
words, so the order of what ran reads as a list.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_build_kit import profiles
from agent_build_kit.config import ProjectConfig, RepoConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.wiring import build_unit_test
from tests.conftest import make_installation
from tests.moved_base_fakes import Profile, affected_lines, moved

LINE = "moved base:"
OWN_TEST = "def test_six():\n    assert True\n"


class Selecting(Profile):
    """The profile's lint, full test run and selected run, each one named word. The selected
    run is `selected`, or what `by_file` names for the first file it is asked about."""

    def __init__(
        self,
        selected: list[list[str]] | None = None,
        by_file: dict[str, list[list[str]]] | None = None,
        cannot_place: str | None = None,
    ) -> None:
        self.selected = selected
        self.by_file = by_file or {}
        self.cannot_place = cannot_place
        self.asked: list[tuple[str, list[str], list[str]]] = []

    def affected_test_commands(
        self,
        repo: Path,
        changed_files: list[str],
        failed_ids: list[str],
        *,
        seed: Path,
        root_extras: list[str],
        **_workers: object,
    ) -> list[list[str]] | None:
        self.asked.append((repo.name, changed_files, failed_ids))
        if repo.name == self.cannot_place:
            return None
        chosen = [c for name in changed_files for c in self.by_file.get(name, [])]
        return chosen or self.selected


def real_test_commands(
    self: Profile, repo: Path, changed: list[str], *, root_extras: list[str], **_workers: object
) -> list[list[str]]:
    return [[sys.executable, "-c", "pass"]]


class WithoutTheHook:
    """A profile that has no `affected_test_commands`, whatever else it does."""

    def __init__(self, inner: Profile) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        if name == "affected_test_commands":
            raise AttributeError(name)
        return getattr(self._inner, name)


class Runner:
    """Answers each command with the summary line of the tests it would have run."""

    def __init__(
        self,
        *,
        full: str = "5963 passed in 1.00s",
        own: str = "6 passed in 0.10s",
        affected: str = "8 passed in 0.10s",
        cannot_start: str | None = None,
    ) -> None:
        self.output = {"full": full, "own": own, "affected": affected}
        self.cannot_start = cannot_start
        self.ran: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.ran.append(command)
        if command[0] == self.cannot_start:
            raise FileNotFoundError(command[0])
        if command[0] == "tests":
            out = self.output["own" if len(command) > 1 else "full"]
        else:
            out = self.output.get(command[0], "")
        return subprocess.CompletedProcess(command, 0, out, "")


def moved_base_lines(logged: list[str]) -> list[str]:
    return [line[line.index(LINE) :] for line in logged if LINE in line]


def run_moved(
    tmp_path: Path,
    profile: Any,
    runner: Runner,
    *,
    own: dict[str, str],
    incoming: dict[str, str],
    base: dict[str, str] | None = None,
    projects: list[ProjectConfig] | None = None,
    after_full: bool = False,
    records_data: bool = False,
    workspace: Installation | None = None,
) -> tuple[bool, list[str]]:
    """Unit-test on a unit moved onto a base that gained `incoming`; with `after_full`, a full
    run on the same runner comes first, as the unit's earlier check. Returns the verdict and
    what was logged by the moved run. `records_data` is the repo's `checks.affected` mode
    `profile`, under which full runs keep the data a selection reads."""
    if workspace is None:
        make_installation(tmp_path / "planning", limits={"unit_test_repeat_runs": 1})
    repo, old_base = moved(tmp_path, own=own, incoming=incoming, base=base)
    logged: list[str] = []
    repo_config = (
        RepoConfig(path=repo, changelog=None, checks={"affected": {"mode": "profile"}})
        if records_data
        else None
    )
    unit_test = build_unit_test(
        profile=profile, run=runner, log=logged.append, projects=projects, repo=repo_config
    )
    if after_full:
        assert unit_test(cwd=repo, base="main")[0]
    logged.clear()
    runner.ran.clear()
    passed, _ = unit_test(cwd=repo, base="main", moved_from=old_base)
    return passed, logged


def test_a_move_over_disjoint_files_runs_lint_the_own_tests_and_the_profiles_selection(
    tmp_path: Path,
) -> None:
    runner = Runner()
    profile = Selecting([["affected"]])

    passed, _ = run_moved(
        tmp_path,
        profile,
        runner,
        own={"a.py": "a = 2\n", "tests/test_own.py": OWN_TEST},
        incoming={"b.py": "b = 2\n"},
    )

    assert passed
    assert runner.ran == [["lint"], ["tests", "tests/test_own.py::test_six"], ["affected"]]
    assert ["tests"] not in runner.ran, "the full test commands did not run"


def test_the_unit_and_the_move_are_asked_about_as_one_list_with_no_failed_ids(
    tmp_path: Path,
) -> None:
    runner = Runner()
    profile = Selecting(by_file={"c.py": [["affected", "tests/test_imports_c.py"]]})

    passed, _ = run_moved(
        tmp_path, profile, runner, own={"a.py": "import c\na = 2\n"}, incoming={"c.py": "c = 2\n"}
    )

    assert passed
    (_, files, failed), *rest = profile.asked
    assert not rest, "the profile is asked once, not once for the unit and once for the move"
    assert sorted(files) == ["a.py", "c.py"]
    assert failed == []
    assert ["affected", "tests/test_imports_c.py"] in runner.ran


def test_a_semantic_conflict_with_no_textual_overlap_fails_the_selected_run(
    tmp_path: Path,
) -> None:
    class ImportingTests(Selecting):
        """Selects the tests that import a changed module; the commands are real."""

        def lint_command(self, base: str) -> list[str]:
            return [sys.executable, "-c", "pass"]

        # Bound by assignment: a function named `test_*` in this file is read as a test.
        test_commands = real_test_commands

        def affected_test_commands(
            self,
            repo: Path,
            changed_files: list[str],
            failed_ids: list[str],
            *,
            seed: Path,
            root_extras: list[str],
            **_workers: object,
        ) -> list[list[str]] | None:
            self.asked.append((repo.name, changed_files, failed_ids))
            modules = {Path(name).stem for name in changed_files}
            tests = sorted(
                str(path.relative_to(repo))
                for path in (repo / "tests").glob("test_*.py")
                if any(
                    f"import {m}" in path.read_text() or f"from {m} " in path.read_text()
                    for m in modules
                )
            )
            return [[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests]]

        def serial_rerun_command(self, command: list[str], tests: list[str]) -> list[str]:
            return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests]

        def failed_tests(self, output: str) -> list[str]:
            return [line.split()[1] for line in output.splitlines() if line.startswith("FAILED ")]

    make_installation(tmp_path / "planning", limits={"unit_test_repeat_runs": 1})
    repo, old_base = moved(
        tmp_path,
        base={
            "c.py": "def f(x):\n    return x\n",
            "a.py": "def run():\n    return 1\n",
            "tests/test_a.py": "from a import run\n\n\ndef test_run():\n    assert run() == 1\n",
        },
        own={"a.py": "from c import f\n\n\ndef run():\n    return f(1)\n"},
        incoming={"c.py": "def f(x, y):\n    return x + y\n"},
    )
    profile = ImportingTests()

    passed, message = build_unit_test(profile=profile)(cwd=repo, base="main", moved_from=old_base)

    assert profile.asked, "the profile was asked for the selected tests"
    assert not passed
    assert "test_run" in message


def test_a_profile_that_returns_nothing_runs_the_full_suite_and_says_why(
    tmp_path: Path,
) -> None:
    runner = Runner()

    passed, logged = run_moved(
        tmp_path, Selecting(None), runner, own={"a.py": "a = 2\n"}, incoming={"b.py": "b = 2\n"}
    )

    assert passed
    assert ["tests"] in runner.ran
    (line,) = moved_base_lines(logged)
    assert line.startswith("moved base: ran the full suite (") and "profile" in line


def test_a_profile_without_the_hook_runs_the_full_suite_and_says_why(tmp_path: Path) -> None:
    runner = Runner()

    passed, logged = run_moved(
        tmp_path,
        WithoutTheHook(Selecting([["affected"]])),
        runner,
        own={"a.py": "a = 2\n"},
        incoming={"b.py": "b = 2\n"},
    )

    assert passed
    assert ["tests"] in runner.ran
    (line,) = moved_base_lines(logged)
    assert line.startswith("moved base: ran the full suite (") and "profile" in line


def test_a_command_that_cannot_start_runs_the_full_suite_and_says_why(tmp_path: Path) -> None:
    runner = Runner(cannot_start="affected")

    passed, logged = run_moved(
        tmp_path,
        Selecting([["affected"]]),
        runner,
        own={"a.py": "a = 2\n"},
        incoming={"b.py": "b = 2\n"},
    )

    assert passed
    assert ["tests"] in runner.ran
    (line,) = moved_base_lines(logged)
    assert line.startswith("moved base: ran the full suite (") and "affected" in line


def test_one_project_the_profile_cannot_place_runs_the_full_suite_in_every_project(
    tmp_path: Path,
) -> None:
    runner = Runner()
    profile = Selecting([["affected"]], cannot_place="svc-b")

    with profiles.registered(profile):
        passed, logged = run_moved(
            tmp_path,
            profile,
            runner,
            base={"svc-a/m.py": "m = 1\n", "svc-b/m.py": "m = 1\n", "README.md": "x\n"},
            own={"svc-a/m.py": "m = 2\n", "svc-b/m.py": "m = 2\n"},
            incoming={"README.md": "y\n"},
            projects=[ProjectConfig(path="svc-a"), ProjectConfig(path="svc-b")],
        )

    assert passed
    assert runner.ran.count(["tests"]) == 2, "each project ran its full tests"
    (line,) = moved_base_lines(logged)
    assert line.startswith("moved base: ran the full suite (") and "svc-b" in line


def test_the_line_counts_the_tests_own_and_selected_against_the_last_full_run(
    tmp_path: Path,
) -> None:
    passed, logged = run_moved(
        tmp_path,
        Selecting([["affected"]]),
        Runner(),
        own={"a.py": "a = 2\n", "tests/test_own.py": OWN_TEST},
        incoming={"b.py": "b = 2\n"},
        after_full=True,
    )

    assert passed
    assert moved_base_lines(logged) == ["moved base: ran 14 of 5963 tests (own 6, affected 8)"]


def test_the_line_omits_the_total_when_no_full_run_is_known(tmp_path: Path) -> None:
    passed, logged = run_moved(
        tmp_path,
        Selecting([["affected"]]),
        Runner(),
        own={"a.py": "a = 2\n", "tests/test_own.py": OWN_TEST},
        incoming={"b.py": "b = 2\n"},
    )

    assert passed
    assert moved_base_lines(logged) == ["moved base: ran 14 tests (own 6, affected 8)"]


def test_an_empty_selection_is_a_pass_with_zero_tests_and_is_logged(tmp_path: Path) -> None:
    runner = Runner()

    passed, logged = run_moved(
        tmp_path, Selecting([]), runner, own={"a.py": "a = 2\n"}, incoming={"b.py": "b = 2\n"}
    )

    assert passed
    assert ["tests"] not in runner.ran
    assert moved_base_lines(logged) == ["moved base: ran 0 tests (own 0, affected 0)"]


PROJECT_BASE = {"svc-a/m.py": "m = 1\n", "svc-b/m.py": "m = 1\n", "README.md": "x\n"}
TWO_PROJECTS = [ProjectConfig(path="svc-a"), ProjectConfig(path="svc-b")]


def moved_in_projects(tmp_path: Path, incoming: dict[str, str]) -> tuple[Runner, list[str]]:
    """A unit changing `svc-a/m.py` moved over `incoming`; what ran and the line logged."""
    runner = Runner()
    profile = Selecting([["affected"]])
    with profiles.registered(profile):
        passed, logged = run_moved(
            tmp_path,
            profile,
            runner,
            base=PROJECT_BASE,
            own={"svc-a/m.py": "m = 2\n"},
            incoming=incoming,
            projects=TWO_PROJECTS,
        )
    assert passed
    return runner, moved_base_lines(logged)


def test_a_file_outside_every_project_that_is_not_a_document_runs_the_full_suite(
    tmp_path: Path,
) -> None:
    runner, (line,) = moved_in_projects(tmp_path, {"deps.lock": "pinned\n"})

    assert ["tests"] in runner.ran
    assert line.startswith("moved base: ran the full suite (") and "deps.lock" in line
    assert "outside the unit's projects" in line


def test_a_file_in_a_project_the_unit_did_not_touch_runs_the_full_suite(tmp_path: Path) -> None:
    runner, (line,) = moved_in_projects(tmp_path, {"svc-b/m.py": "m = 3\n"})

    assert ["tests"] in runner.ran
    assert line.startswith("moved base: ran the full suite (") and "svc-b/m.py" in line


def test_a_document_outside_every_project_stays_scoped(tmp_path: Path) -> None:
    runner, (line,) = moved_in_projects(tmp_path, {"README.md": "y\n"})

    assert ["tests"] not in runner.ran
    assert "full suite" not in line


def seeded_tests(
    self: Profile, repo: Path, changed: list[str], *, root_extras: list[str], **_workers: object
) -> list[list[str]]:
    return [["uv", "run", "pytest", "tests"]]


class SeedProfile(Profile):
    """The python-uv profile's own selection, over one pytest command."""

    test_commands = seeded_tests


class SeedingRunner(Runner):
    """Writes the selection data a seeded run records, where the command says."""

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[0] == "env":
            Path(command[1].split("=", 1)[1]).write_bytes(b"recorded")
        return super().__call__(command, **kwargs)


def test_a_full_run_records_the_data_a_later_moved_run_selects_by(tmp_path: Path) -> None:
    runner = SeedingRunner()

    passed, logged = run_moved(
        tmp_path,
        SeedProfile(),
        runner,
        own={"a.py": "a = 2\n"},
        incoming={"b.py": "b = 2\n"},
        after_full=True,
        records_data=True,
    )

    assert passed
    assert "--testmon-forceselect" in runner.ran[-1] and "--testmon" not in runner.ran[-1]
    assert "--testmon-noselect" not in runner.ran[-1]
    (line,) = moved_base_lines(logged)
    assert "full suite" not in line


def test_with_checks_affected_off_no_data_is_kept_and_the_line_says_so(tmp_path: Path) -> None:
    runner = SeedingRunner()

    passed, logged = run_moved(
        tmp_path,
        SeedProfile(),
        runner,
        own={"a.py": "a = 2\n"},
        incoming={"b.py": "b = 2\n"},
        after_full=True,
    )

    assert passed
    assert not any("--testmon" in word for command in runner.ran for word in command)
    (line,) = moved_base_lines(logged)
    assert line.startswith("moved base: ran the full suite (") and "checks.affected" in line


def test_a_passing_scoped_move_writes_one_ledger_line_with_the_counts_the_log_gives(
    tmp_path: Path,
) -> None:
    workspace = make_installation(tmp_path / "planning", limits={"unit_test_repeat_runs": 1})

    passed, logged = run_moved(
        tmp_path,
        Selecting([["affected"]]),
        Runner(),
        own={"a.py": "a = 2\n", "tests/test_own.py": OWN_TEST},
        incoming={"b.py": "b = 2\n"},
        after_full=True,
        workspace=workspace,
    )

    assert passed
    assert moved_base_lines(logged) == ["moved base: ran 14 of 5963 tests (own 6, affected 8)"]
    (line,) = affected_lines(workspace)
    assert (line["outcome"], line["selected"], line["total"]) == ("moved", 14, 5963)
