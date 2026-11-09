"""The Python profile in the unit-test runner's fix round, and the ledger line each selected
run leaves (spec: affected-tests-in-fix-rounds).

The command runner is the faked boundary, answering a test run with pytest's summary line
and the time it took on a fake clock; the profile is the real python-uv one.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.config import RepoConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.command_limit import TIMED_OUT_EXIT
from agent_build_kit.pipeline.scratch import ensure_scratch, selection_seed
from agent_build_kit.pipeline.selection_base import hand_over, refresh_base_data
from agent_build_kit.pipeline.shell import git, git_out
from agent_build_kit.pipeline.usage_ledger import forget_told
from agent_build_kit.pipeline.wiring import build_unit_test
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
        return "--testmon-forceselect" in command or any("::" in word for word in command)

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


def unit_test_for(
    repo: Path, runner: Runner, mode: str = "profile", log: list[str] | None = None
) -> Callable[..., tuple[bool, str]]:
    return build_unit_test(
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

    unit_test_for(repo, on)(cwd=repo, base="main")
    unit_test_for(repo, off, mode="off")(cwd=repo, base="main")

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

    passed, _ = unit_test_for(repo, runner)(cwd=repo, base="main", failed_output=FAILED_OUTPUT)

    assert passed
    (selected,) = runner.selected_runs()
    assert ID in selected and not any("testmon" in word for word in selected)
    assert len(runner.full_runs()) == 1


def test_a_selected_run_writes_one_line_with_counts_the_saving_and_the_confirming_outcome(
    tmp_path: Path, clock: FakeClock, workspace: Installation
) -> None:
    repo = repo_at(tmp_path)
    unit_test = unit_test_for(repo, Runner(clock))

    unit_test(cwd=repo, base="main")
    assert affected_lines(workspace) == [], "a full check is not a selected run"
    unit_test(cwd=repo, base="main", failed_output=FAILED_OUTPUT)

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
    unit_test = unit_test_for(repo, runner)
    unit_test(cwd=repo, base="main")
    runner.full = (1, 100, "1 failed, 9 passed in 100.00s")

    passed, _ = unit_test(cwd=repo, base="main", failed_output=FAILED_OUTPUT)

    assert not passed
    (line,) = affected_lines(workspace)
    assert line["outcome"] == "disagreed"


NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def base_recording_handed_to(tmp_path: Path, worktree: Path, *, age_hours: float) -> None:
    """A base repository with a kept recording `age_hours` old at `NOW`, handed to `worktree`."""
    base = tmp_path / "base"
    base.mkdir()
    git(base, "init", "-q", "-b", "main")
    git(base, "config", "user.email", "a@example.com")
    git(base, "config", "user.name", "a")
    (base / "x.py").write_text("x = 1\n")
    git(base, "add", "-A")
    git(base, "commit", "-qm", "base")
    store = tmp_path / "state" / "selection-base"

    def record(_commit: str, data: Path) -> None:
        data.write_bytes(b"recorded")

    refresh_base_data(
        store=store,
        repo=base,
        base="main",
        record=record,
        kept=3,
        max_age_hours=12,
        now=lambda: NOW - timedelta(hours=age_hours),
    )
    assert hand_over(store=store, repo=base, base="main", worktree=worktree) is not None


def ledger_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def ledgered_unit_test(repo: Path, runner: Runner, ledger: Path) -> Callable[..., tuple[bool, str]]:
    return build_unit_test(
        run=runner,
        changed=lambda *a: ["src/x.py"],
        repo=RepoConfig(path=repo, changelog=None, checks={"affected": {"mode": "profile"}}),
        test_runs=ledger,
        now=lambda: NOW,
        machine=lambda: {"load": [1.0, 1.0, 1.0]},
    )


def test_a_first_round_on_the_bases_data_selects_and_does_not_start_with_a_full_run(
    tmp_path: Path, clock: FakeClock
) -> None:
    repo = repo_at(tmp_path / "unit")
    base_recording_handed_to(tmp_path, repo, age_hours=5)
    runner = Runner(clock)

    passed, _ = unit_test_for(repo, runner)(cwd=repo, base="main")

    assert passed
    first = next(c for c in runner.ran if "pytest" in c)
    assert "--testmon-forceselect" in first and "--testmon-noselect" not in first


def test_a_first_round_with_no_recording_is_a_full_run_that_records(
    tmp_path: Path, clock: FakeClock
) -> None:
    repo = repo_at(tmp_path / "unit")
    runner = Runner(clock)
    ledger = tmp_path / "test-runs.jsonl"

    ledgered_unit_test(repo, runner, ledger)(cwd=repo, base="main")

    assert ledger_rows(ledger)[0]["data_source"] == "none"
    first = next(c for c in runner.ran if "pytest" in c)
    assert not Runner.is_selected(first)
    assert any("testmon" in word for word in first)
    assert any(str(selection_seed(repo)) in word for word in first)


@pytest.mark.parametrize("source", ["none", "own", "base"])
def test_the_ledger_row_names_where_the_runs_selection_data_came_from(
    tmp_path: Path, clock: FakeClock, source: str
) -> None:
    repo = repo_at(tmp_path / "unit")
    if source == "own":
        selection_seed(repo).write_bytes(b"recorded by the unit's own run")
    if source == "base":
        base_recording_handed_to(tmp_path, repo, age_hours=5)
    ledger = tmp_path / "test-runs.jsonl"

    ledgered_unit_test(repo, Runner(clock), ledger)(cwd=repo, base="main")

    (row,) = ledger_rows(ledger)
    assert row["data_source"] == source
    assert row["data_age_hours"] == (5.0 if source == "base" else None)


def test_a_later_round_after_a_base_start_names_the_units_own_data(
    tmp_path: Path, clock: FakeClock
) -> None:
    repo = repo_at(tmp_path / "unit")
    base_recording_handed_to(tmp_path, repo, age_hours=5)
    ledger = tmp_path / "test-runs.jsonl"
    unit_test = ledgered_unit_test(repo, Runner(clock), ledger)

    unit_test(cwd=repo, base="main")
    unit_test(cwd=repo, base="main", failed_output=FAILED_OUTPUT)

    rows = ledger_rows(ledger)
    assert [row["data_source"] for row in rows] == ["base", "own"]
    assert rows[1]["data_age_hours"] is None


def test_a_failed_selected_run_reads_not_run(
    tmp_path: Path, clock: FakeClock, workspace: Installation
) -> None:
    repo = repo_at(tmp_path)
    runner = Runner(clock, selected=(1, 10, "1 failed in 9.00s"))
    unit_test = unit_test_for(repo, runner)
    unit_test(cwd=repo, base="main")

    passed, _ = unit_test(cwd=repo, base="main", failed_output=FAILED_OUTPUT)

    assert not passed
    (line,) = affected_lines(workspace)
    assert line["outcome"] == "not_run"
    assert len(runner.full_runs()) == 1


def test_the_saving_is_never_negative(
    tmp_path: Path, clock: FakeClock, workspace: Installation
) -> None:
    repo = repo_at(tmp_path)
    runner = Runner(clock, full=(0, 5, "10 passed in 5.00s"), selected=(0, 20, "1 passed in 19s"))
    unit_test = unit_test_for(repo, runner)
    unit_test(cwd=repo, base="main")

    unit_test(cwd=repo, base="main", failed_output=FAILED_OUTPUT)

    (line,) = affected_lines(workspace)
    assert line["saved_seconds"] == 0


def test_the_saving_is_absent_when_the_unit_has_no_full_run_to_compare_with(
    tmp_path: Path, clock: FakeClock, workspace: Installation
) -> None:
    repo = repo_at(tmp_path)

    unit_test_for(repo, Runner(clock))(cwd=repo, base="main", failed_output=FAILED_OUTPUT)

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
    unit_test = unit_test_for(repo, runner, log=log)

    first, _ = unit_test(cwd=repo, base="main", failed_output=FAILED_OUTPUT)
    second, _ = unit_test(cwd=repo, base="main", failed_output=FAILED_OUTPUT)

    assert first and second
    assert len(runner.selected_runs()) == 2
    assert sum("usage ledger" in line for line in log) == 1, log


def test_a_seeded_selection_runs_with_the_plugin_and_its_count_reaches_the_ledger(
    tmp_path: Path, clock: FakeClock, workspace: Installation
) -> None:
    repo = repo_at(tmp_path)
    selection_seed(repo).write_bytes(b"recorded")
    runner = Runner(clock, selected=(0, 10, "4 passed in 9.00s"))

    passed, _ = unit_test_for(repo, runner)(cwd=repo, base="main", failed_output=FAILED_OUTPUT)

    assert passed
    (selected,) = runner.selected_runs()
    assert "--testmon-forceselect" in selected and "--testmon" not in selected
    assert "--testmon-noselect" not in selected
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
    unit_test = unit_test_for(repo, runner, log=log)

    passed, output = unit_test(
        cwd=repo, base="main", failed_output=FAILED_OUTPUT if with_failure else ""
    )

    assert passed, output
    plain = [c for c in runner.full_runs() if not any("testmon" in w for w in c)]
    assert plain, runner.ran
    assert any("selection tooling" in line for line in log), log


def test_a_selected_run_that_timed_out_is_a_timeout_and_the_full_suite_does_not_stand_in(
    tmp_path: Path, clock: FakeClock
) -> None:
    """A run killed at its time limit prints no result line, as a run that could not start does;
    it is the first of those that cost the unit a second hour-long run."""
    repo = repo_at(tmp_path)
    selection_seed(repo).write_bytes(b"recorded")
    runner = Runner(clock, selected=(TIMED_OUT_EXIT, 3600, ""))
    log: list[str] = []

    passed, output = unit_test_for(repo, runner, log=log)(
        cwd=repo, base="main", failed_output=FAILED_OUTPUT
    )

    assert not passed and "exit 124" in output
    assert [Runner.is_selected(c) for c in runner.ran if "pytest" in c] == [True]
    assert not any("selection tooling" in line for line in log), log


def test_a_first_recording_run_that_timed_out_is_a_timeout_and_no_second_full_run_follows(
    tmp_path: Path, clock: FakeClock
) -> None:
    repo = repo_at(tmp_path)
    runner = Runner(clock, full=(TIMED_OUT_EXIT, 3600, ""))
    log: list[str] = []

    passed, output = unit_test_for(repo, runner, log=log)(cwd=repo, base="main")

    assert not passed and "exit 124" in output
    assert len([c for c in runner.ran if "pytest" in c]) == 1
    assert not any("selection tooling" in line for line in log), log


def test_the_log_names_the_program_not_the_env_words_before_it(
    tmp_path: Path, clock: FakeClock
) -> None:
    repo = repo_at(tmp_path)
    runner = Runner(clock, no_plugin=True)
    log: list[str] = []

    unit_test_for(repo, runner, log=log)(cwd=repo, base="main")

    said = [line for line in log if "selection tooling" in line]
    assert said and "uv could not" in said[0] and "env" not in said[0]


def test_the_repos_root_extras_reach_the_profiles_selection(
    tmp_path: Path, clock: FakeClock
) -> None:
    class Asked(PythonUvProfile):
        extras: list[str] | None = None

        def affected_test_commands(
            self, repo, changed_files, failed_ids, *, seed, root_extras, **_workers
        ):
            self.extras = root_extras
            return None

    repo = repo_at(tmp_path)
    profile = Asked()
    unit_test = build_unit_test(
        run=Runner(clock),
        changed=lambda *a: ["tests/test_x.py"],
        profile=profile,
        root_extras=["httpx"],
        repo=RepoConfig(path=repo, changelog=None, checks={"affected": {"mode": "profile"}}),
    )

    unit_test(cwd=repo, base="main", failed_output=FAILED_OUTPUT)

    assert profile.extras == ["httpx"]


def test_a_seeded_selection_that_picks_nothing_is_a_pass_the_full_suite_confirms(
    tmp_path: Path, clock: FakeClock
) -> None:
    repo = repo_at(tmp_path)
    selection_seed(repo).write_bytes(b"recorded")
    nothing = PythonUvProfile().no_tests_collected_exit
    runner = Runner(clock, selected=(nothing, 1, "collected 10 items\n\n10 deselected in 0.1s"))
    log: list[str] = []

    passed, output = unit_test_for(repo, runner, log=log)(
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

    passed, output = unit_test_for(repo, runner, log=log)(cwd=repo, base="main")

    assert passed, output
    serial = [c for c in runner.ran if "pytest" in c and "serial" in c]
    assert len(serial) == 1 and any("testmon" in w for w in serial[0])
    assert not any("selection tooling" in line for line in log), log
