"""A selected run that ran tests but whose output says testmon deactivated the selection is
lost selection tooling: the pipeline says why and the full suite stands in once (spec:
affected-test-selection).

The command runner is the faked boundary, answering with the raw output pytest-testmon prints;
the profile is the real python-uv one.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit.config import RepoConfig
from agent_build_kit.pipeline.scratch import selection_seed
from agent_build_kit.pipeline.wiring import build_unit_test
from tests.conftest import make_installation
from tests.moved_base_fakes import Profile, moved

ID = "tests/test_a.py::test_one"
FAILED_OUTPUT = f"FAILED {ID} - assert 1 == 2"
DEACTIVATED = "testmon: selection automatically deactivated because {reason}"
DEACTIVATED_LINE = "affected tests: selection was deactivated ({reason}), running the full suite"


class Runner:
    """A selection prints `selected_output`; any other test run passes with ten tests."""

    def __init__(self, selected_output: str) -> None:
        self.selected_output = selected_output
        self.ran: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.ran.append(command)
        if command[0] == "env":
            Path(command[1].split("=", 1)[1]).write_bytes(b"recorded")
        if "--testmon-forceselect" in command:
            return subprocess.CompletedProcess(command, 0, self.selected_output, "")
        if "pytest" in command:
            return subprocess.CompletedProcess(command, 0, "10 passed in 1.00s", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    def full_runs(self) -> list[list[str]]:
        return [c for c in self.ran if "pytest" in c and "--testmon-forceselect" not in c]


def fix_round(tmp_path: Path, selected_output: str) -> tuple[bool, list[str], Runner]:
    """A fix round in a repo whose selection data is recorded, so the failed test is selected."""
    repo = tmp_path / "plain"
    (repo / "tests").mkdir(parents=True)
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\n')
    selection_seed(repo).parent.mkdir(parents=True, exist_ok=True)
    selection_seed(repo).write_bytes(b"recorded")
    runner = Runner(selected_output)
    logged: list[str] = []
    unit_test = build_unit_test(
        run=runner,
        changed=lambda *a: ["src/x.py"],
        repo=RepoConfig(path=repo, changelog=None, checks={"affected": {"mode": "profile"}}),
        log=logged.append,
    )
    passed, _ = unit_test(cwd=repo, base="main", failed_output=FAILED_OUTPUT)
    return passed, logged, runner


def test_a_deactivated_selection_in_a_fix_round_is_logged_and_the_full_suite_runs_once(
    tmp_path: Path,
) -> None:
    reason = "-m was used"
    output = f"3 passed in 0.10s\n{DEACTIVATED.format(reason=reason)}"

    passed, logged, runner = fix_round(tmp_path, output)

    assert passed
    assert any(DEACTIVATED_LINE.format(reason=reason) in line for line in logged), logged
    assert len(runner.full_runs()) == 1, runner.ran


def test_the_deactivated_line_names_the_reason_testmon_gave(tmp_path: Path) -> None:
    reason = "-k was used"

    _, logged, _ = fix_round(tmp_path, f"3 passed\n{DEACTIVATED.format(reason=reason)}")

    assert any(DEACTIVATED_LINE.format(reason=reason) in line for line in logged), logged


def seeded_tests(
    self: Profile, repo: Path, changed: list[str], *, root_extras: list[str], **_workers: object
) -> list[list[str]]:
    return [["uv", "run", "pytest", "tests"]]


class SeedProfile(Profile):
    """The python-uv profile's own selection, over one pytest command."""

    test_commands = seeded_tests


def moved_run(tmp_path: Path, selected_output: str) -> tuple[bool, list[str], Runner]:
    """A recorded full run, then the same unit moved onto a base that gained a file."""
    make_installation(tmp_path / "planning", limits={"unit_test_repeat_runs": 1})
    repo, old_base = moved(tmp_path, own={"a.py": "a = 2\n"}, incoming={"b.py": "b = 2\n"})
    runner = Runner(selected_output)
    logged: list[str] = []
    unit_test = build_unit_test(
        profile=SeedProfile(),
        run=runner,
        log=logged.append,
        repo=RepoConfig(path=repo, changelog=None, checks={"affected": {"mode": "profile"}}),
    )
    assert unit_test(cwd=repo, base="main")[0]
    logged.clear()
    runner.ran.clear()
    passed, _ = unit_test(cwd=repo, base="main", moved_from=old_base)
    return passed, logged, runner


def test_a_deactivated_selection_on_a_moved_base_adds_its_reason_and_runs_the_full_suite_once(
    tmp_path: Path,
) -> None:
    reason = "-m was used"
    output = f"3 passed\n{DEACTIVATED.format(reason=reason)}"

    passed, logged, runner = moved_run(tmp_path / "deactivated", output)
    _, _, baseline = moved_run(tmp_path / "baseline", "3 passed")

    assert passed
    assert any(DEACTIVATED_LINE.format(reason=reason) in line for line in logged), logged
    (line,) = [line for line in logged if "moved base:" in line]
    assert line[line.index("moved base:") :].startswith("moved base: ran the full suite (")
    assert reason in line
    assert len(runner.full_runs()) == len(baseline.full_runs()) + 1
