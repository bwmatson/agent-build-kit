"""The Python profile in the tier 1 runner's fix round, and the ledger line each selected
run leaves (spec: affected-tests-in-fix-rounds).

The command runner is the faked boundary, answering a test run with pytest's summary line
and the time it took on a fake clock; the profile is the real python-uv one.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from agent_build_kit.config import RepoConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.usage_ledger import forget_told
from agent_build_kit.pipeline.wiring import build_tier1
from tests.fake_clock import FakeClock, install

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
    ) -> None:
        self.clock = clock
        self.full = full
        self.selected = selected
        self.ran: list[list[str]] = []

    def __call__(self, command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        self.ran.append(command)
        if "pytest" not in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        code, seconds, output = self.selected if self.is_selected(command) else self.full
        self.clock.advance(seconds)
        return subprocess.CompletedProcess(command, code, output, "")

    @staticmethod
    def is_selected(command: list[str]) -> bool:
        return any("::" in word for word in command)

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


def affected_lines(workspace: Installation) -> list[dict]:
    path = workspace.state_dir / "usage-ledger.jsonl"
    lines = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [line for line in lines if line.get("kind") == "affected"]


def test_the_first_full_run_records_the_seed_data_in_the_units_worktree(
    tmp_path: Path, clock: FakeClock
) -> None:
    repo = repo_at(tmp_path)
    on, off = Runner(clock), Runner(clock)

    tier1_for(repo, on)(cwd=repo, base="main")
    tier1_for(repo, off, mode="off")(cwd=repo, base="main")

    (recording,) = on.full_runs()
    assert any("testmon" in word for word in recording)
    assert any(str(repo / ".abk-affected") in word for word in recording)
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
    assert sum("ledger" in line for line in log) == 1, log
