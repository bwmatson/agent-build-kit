"""The Python profile in the tier 1 runner's fix round, and the ledger line each selected
run leaves (spec: affected-tests-in-fix-rounds).

The command runner is the faked boundary, answering a test run with pytest's summary line
and the time it took on a fake clock; the profile is the real python-uv one.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from agent_build_kit.config import RepoConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.scratch import ensure_scratch, selection_seed
from agent_build_kit.pipeline.shell import git, git_out
from agent_build_kit.pipeline.usage_ledger import forget_told
from agent_build_kit.pipeline.wiring import build_tier1
from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.fake_clock import FakeClock, install
from tests.moved_base_fakes import affected_lines

ID = "tests/test_a.py::test_one"
FAILED_OUTPUT = f"FAILED {ID} - assert 1 == 2"
UNIT = "add-marker/1"


class Runner:
    """Lint takes no time; a test run takes what it is told and ends as it is told."""

    def __init__(
        self,
        clock: FakeClock,
        *,
        full: tuple[int, int, str] = (0, 100, "10 passed in 100.00s"),
        selected: tuple[int, int, str] = (0, 10, "1 passed in 9.00s"),
        no_plugin: bool = False,
    ) -> None:
        self.no_plugin = no_plugin
        self.clock = clock
        self.full = full
        self.selected = selected
        self.ran: list[list[str]] = []

    def __call__(self, command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        self.ran.append(command)
        if "pytest" not in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        if self.no_plugin and any("testmon" in word for word in command):
            return subprocess.CompletedProcess(
                command, 2, "", "error: No solution found: pytest-testmon"
            )
        code, seconds, output = self.selected if self.is_selected(command) else self.full
        self.clock.advance(seconds)
        return subprocess.CompletedProcess(command, code, output, "")

    @staticmethod
    def is_selected(command: list[str]) -> bool:
        return "--testmon" in command or any("::" in word for word in command)

    def full_runs(self) -> list[list[str]]:
        return [c for c in self.ran if "pytest" in c and not self.is_selected(c)]

    def selected_runs(self) -> list[list[str]]:
        return [c for c in self.ran if "pytest" in c and self.is_selected(c)]


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return install(monkeypatch)


@pytest.fixture(autouse=True)
def unit() -> Iterator[None]:
    token = spans.current_unit.set((UNIT, "add-marker", "checks", 2))
    forget_told()
    yield
    spans.current_unit.reset(token)


def repo_at(tmp_path: Path) -> Path:
    repo = tmp_path / "plain"
    (repo / "tests").mkdir(parents=True)
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\n')
    return repo


def tier1_for(
    repo: Path, runner: Runner, mode: str = "profile", log: list[str] | None = None
) -> Callable[..., tuple[bool, str]]:
    return build_tier1(
        run=runner,
        changed=lambda *a: ["src/x.py"],
        repo=RepoConfig(path=repo, changelog=None, checks={"affected": {"mode": mode}}),
        log=log.append if log is not None else None,
    )


def test_the_first_full_run_records_the_seed_data_in_the_units_worktree(
    tmp_path: Path, clock: FakeClock
) -> None:
    repo = repo_at(tmp_path)
    on, off = Runner(clock), Runner(clock)

    tier1_for(repo, on)(cwd=repo, base="main")
    tier1_for(repo, off, mode="off")(cwd=repo, base="main")

    (recording,) = on.full_runs()
    assert any("testmon" in word for word in recording)
    assert any(str(selection_seed(repo)) in word for word in recording)
    (plain,) = off.full_runs()
    assert not any("testmon" in word for word in plain)


def test_a_rebuilt_worktree_with_no_seed_data_falls_back_to_the_failed_test_without_failing(
    tmp_path: Path, clock: FakeClock
) -> None:
    repo = repo_at(tmp_path)
    runner = Runner(clock)

    passed, _ = tier1_for(repo, runner)(cwd=repo, base="main", failed_output=FAILED_OUTPUT)

    assert passed
    (selected,) = runner.selected_runs()
    assert ID in selected and not any("testmon" in word for word in selected)
    assert len(runner.full_runs()) == 1


def test_a_selected_run_writes_one_line_with_counts_the_saving_and_the_confirming_outcome(
    tmp_path: Path, clock: FakeClock, workspace: Installation
) -> None:
    repo = repo_at(tmp_path)
    tier1 = tier1_for(repo, Runner(clock))

    tier1(cwd=repo, base="main")
    assert affected_lines(workspace) == [], "a full check is not a selected run"
    tier1(cwd=repo, base="main", failed_output=FAILED_OUTPUT)

    (line,) = affected_lines(workspace)
    assert (line["unit"], line["node"], line["round"]) == (UNIT, "checks", 2)
    assert (line["selected"], line["total"]) == (1, 10)
    assert line["saved_seconds"] == 90
    assert line["outcome"] == "agreed"


def test_a_full_failure_after_a_selected_pass_reads_disagreed(
    tmp_path: Path, clock: FakeClock, workspace: Installation
) -> None:
    repo = repo_at(tmp_path)
    runner = Runner(clock)
    tier1 = tier1_for(repo, runner)
    tier1(cwd=repo, base="main")
    runner.full = (1, 100, "1 failed, 9 passed in 100.00s")

    passed, _ = tier1(cwd=repo, base="main", failed_output=FAILED_OUTPUT)

    assert not passed
    (line,) = affected_lines(workspace)
    assert line["outcome"] == "disagreed"


def test_a_failed_selected_run_reads_not_run(
    tmp_path: Path, clock: FakeClock, workspace: Installation
) -> None:
    repo = repo_at(tmp_path)
    runner = Runner(clock, selected=(1, 10, "1 failed in 9.00s"))
    tier1 = tier1_for(repo, runner)
    tier1(cwd=repo, base="main")

    passed, _ = tier1(cwd=repo, base="main", failed_output=FAILED_OUTPUT)

    assert not passed
    (line,) = affected_lines(workspace)
    assert line["outcome"] == "not_run"
    assert len(runner.full_runs()) == 1


def test_the_saving_is_never_negative(
    tmp_path: Path, clock: FakeClock, workspace: Installation
) -> None:
    repo = repo_at(tmp_path)
    runner = Runner(clock, full=(0, 5, "10 passed in 5.00s"), selected=(0, 20, "1 passed in 19s"))
    tier1 = tier1_for(repo, runner)
    tier1(cwd=repo, base="main")

    tier1(cwd=repo, base="main", failed_output=FAILED_OUTPUT)

    (line,) = affected_lines(workspace)
    assert line["saved_seconds"] == 0


def test_the_saving_is_absent_when_the_unit_has_no_full_run_to_compare_with(
    tmp_path: Path, clock: FakeClock, workspace: Installation
) -> None:
    repo = repo_at(tmp_path)

    tier1_for(repo, Runner(clock))(cwd=repo, base="main", failed_output=FAILED_OUTPUT)

    (line,) = affected_lines(workspace)
    assert line.get("saved_seconds") is None
    assert line["selected"] == 1


def test_an_unwritable_ledger_does_not_fail_the_run_and_is_reported_once(
    tmp_path: Path, clock: FakeClock, workspace: Installation
) -> None:
    repo = repo_at(tmp_path)
    (workspace.state_dir / "usage-ledger.jsonl").mkdir(parents=True)
    runner = Runner(clock)
    log: list[str] = []
    tier1 = tier1_for(repo, runner, log=log)

    first, _ = tier1(cwd=repo, base="main", failed_output=FAILED_OUTPUT)
    second, _ = tier1(cwd=repo, base="main", failed_output=FAILED_OUTPUT)

    assert first and second
    assert len(runner.selected_runs()) == 2
    assert sum("usage ledger" in line for line in log) == 1, log


def test_a_seeded_selection_runs_with_the_plugin_and_its_count_reaches_the_ledger(
    tmp_path: Path, clock: FakeClock, workspace: Installation
) -> None:
    repo = repo_at(tmp_path)
    selection_seed(repo).write_bytes(b"recorded")
    runner = Runner(clock, selected=(0, 10, "4 passed in 9.00s"))

    passed, _ = tier1_for(repo, runner)(cwd=repo, base="main", failed_output=FAILED_OUTPUT)

    assert passed
    (selected,) = runner.selected_runs()
    assert "--testmon" in selected and "--testmon-noselect" not in selected
    (line,) = affected_lines(workspace)
    assert line["selected"] == 4


def test_the_seed_a_full_run_leaves_is_not_work_the_commit_step_would_stage(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "tree"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "a@example.com")
    git(repo, "config", "user.name", "a")
    (repo / "x.py").write_text("x = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    ensure_scratch(repo)

    seed = selection_seed(repo)
    for name in (seed.name, f"{seed.name}-wal", f"{seed.name}-shm"):
        (seed.parent / name).write_bytes(b"sqlite")
    git(repo, "add", "-A")

    assert git_out(repo, "status", "--porcelain") == ""


@pytest.mark.parametrize("with_failure", [False, True])
def test_a_plugin_that_cannot_be_had_costs_time_and_never_the_unit(
    tmp_path: Path, clock: FakeClock, with_failure: bool
) -> None:
    repo = repo_at(tmp_path)
    selection_seed(repo).write_bytes(b"recorded")
    runner = Runner(clock, no_plugin=True)
    log: list[str] = []
    tier1 = tier1_for(repo, runner, log=log)

    passed, output = tier1(
        cwd=repo, base="main", failed_output=FAILED_OUTPUT if with_failure else ""
    )

    assert passed, output
    plain = [c for c in runner.full_runs() if not any("testmon" in w for w in c)]
    assert plain, runner.ran
    assert any("selection tooling" in line for line in log), log


def test_the_log_names_the_program_not_the_env_words_before_it(
    tmp_path: Path, clock: FakeClock
) -> None:
    repo = repo_at(tmp_path)
    runner = Runner(clock, no_plugin=True)
    log: list[str] = []

    tier1_for(repo, runner, log=log)(cwd=repo, base="main")

    said = [line for line in log if "selection tooling" in line]
    assert said and "uv could not" in said[0] and "env" not in said[0]


def test_the_repos_root_extras_reach_the_profiles_selection(
    tmp_path: Path, clock: FakeClock
) -> None:
    class Asked(PythonUvProfile):
        extras: list[str] | None = None

        def affected_test_commands(self, repo, changed_files, failed_ids, *, seed, root_extras):
            self.extras = root_extras
            return None

    repo = repo_at(tmp_path)
    profile = Asked()
    tier1 = build_tier1(
        run=Runner(clock),
        changed=lambda *a: ["tests/test_x.py"],
        profile=profile,
        root_extras=["httpx"],
        repo=RepoConfig(path=repo, changelog=None, checks={"affected": {"mode": "profile"}}),
    )

    tier1(cwd=repo, base="main", failed_output=FAILED_OUTPUT)

    assert profile.extras == ["httpx"]


def test_a_seeded_selection_that_picks_nothing_is_a_pass_the_full_suite_confirms(
    tmp_path: Path, clock: FakeClock
) -> None:
    repo = repo_at(tmp_path)
    selection_seed(repo).write_bytes(b"recorded")
    nothing = PythonUvProfile().no_tests_collected_exit
    runner = Runner(clock, selected=(nothing, 1, "collected 10 items\n\n10 deselected in 0.1s"))
    log: list[str] = []

    passed, output = tier1_for(repo, runner, log=log)(
        cwd=repo, base="main", failed_output=FAILED_OUTPUT
    )

    assert passed, output
    tests = [c for c in runner.ran if "pytest" in c]
    assert [Runner.is_selected(c) for c in tests] == [True, False]
    assert not any("testmon" in w for w in tests[1]) or "--testmon-noselect" in tests[1]
    assert not any("selection tooling" in line for line in log), log


def test_a_seeded_serial_pass_that_collects_nothing_is_run_once_and_says_nothing(
    tmp_path: Path, clock: FakeClock
) -> None:
    repo = repo_at(tmp_path)
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\ndependencies = ["pytest-xdist"]\n')
    nothing = PythonUvProfile().no_tests_collected_exit

    class EmptySerialPass(Runner):
        def __call__(self, command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
            if "pytest" in command and "serial" in command:
                self.ran.append(command)
                return subprocess.CompletedProcess(command, nothing, "no tests ran in 0.01s", "")
            return super().__call__(command, cwd=cwd)

    runner = EmptySerialPass(clock)
    log: list[str] = []

    passed, output = tier1_for(repo, runner, log=log)(cwd=repo, base="main")

    assert passed, output
    serial = [c for c in runner.ran if "pytest" in c and "serial" in c]
    assert len(serial) == 1 and any("testmon" in w for w in serial[0])
    assert not any("selection tooling" in line for line in log), log
