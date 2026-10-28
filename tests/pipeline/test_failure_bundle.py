"""A failing unit-test run saves a bundle of evidence under `runs/test-failures/`
(spec: test-failure-evidence).

The bundle writer is exercised directly for what it keeps and drops, and through
`build_unit_test` for what a failing run puts in it. The runner answers as the processes would:
git with its porcelain text, the test run with a pytest header and the recorded failure.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Collection, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.flakes import FlakeFound
from agent_build_kit.pipeline.run_log import (
    FAILURE_OUTPUT_CAP,
    RUNS_KEPT,
    failure_bundles_dir,
    write_failure_bundle,
)
from agent_build_kit.pipeline.wiring import build_unit_test
from agent_build_kit.profiles.base import ToolchainProfile
from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.redaction_fakes import NAME, SECRET, known

RECORDED = Path(__file__).resolve().parents[1] / "fixtures" / "external" / "pytest"
START = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)
HEADER = (
    "============================= test session starts ==============================\n"
    "platform linux -- Python 3.13.1, pytest-8.3.3, pluggy-1.5.0\n"
    "plugins: xdist-3.6.1\n"
)
RUN = ["uv", "run", "pytest", "-n", "4", "-q"]


def _bundle(
    directory: Path,
    started: datetime,
    *,
    output: str = "1 failed\n",
    context: dict[str, object] | None = None,
    machine: dict[str, object] | None = None,
    worktree: dict[str, object] | None = None,
    pointed: Collection[Path] = (),
    cap: int = FAILURE_OUTPUT_CAP,
) -> Path:
    return write_failure_bundle(
        directory,
        "add-marker/1",
        "add-marker",
        started,
        output=output,
        context={"command": "pytest"} if context is None else context,
        machine={"start": {}, "end": {}} if machine is None else machine,
        worktree={"before": {}, "after": {}} if worktree is None else worktree,
        pointed=pointed,
        cap=cap,
    )


# --- the writer ---------------------------------------------------------------------


def test_the_bundles_live_in_a_folder_of_the_state_directory(tmp_path: Path) -> None:
    assert failure_bundles_dir(tmp_path) == tmp_path / "test-failures"


def test_a_bundle_is_a_folder_named_for_the_unit_and_the_start_holding_four_files(
    tmp_path: Path,
) -> None:
    path = _bundle(tmp_path, START, output="the whole output\n")

    assert path.parent == tmp_path
    assert path.name == "add-marker-01-20261011-120000"
    assert {child.name for child in path.iterdir()} == {
        "output.txt",
        "context.json",
        "machine.json",
        "worktree.json",
    }
    assert (path / "output.txt").read_text() == "the whole output\n"
    assert json.loads((path / "context.json").read_text()) == {"command": "pytest"}


def test_the_whole_output_is_kept_though_a_record_clips_it(tmp_path: Path) -> None:
    long = "".join(f"line {n}\n" for n in range(2000)) + "1 failed\n"
    assert len(long) > 6000

    path = _bundle(tmp_path, START, output=long)

    assert (path / "output.txt").read_text() == long


def test_the_output_is_redacted_and_so_is_every_other_file(tmp_path: Path) -> None:
    with known():
        path = _bundle(
            tmp_path,
            START,
            output=f"token={SECRET}\n",
            context={"command": f"pytest --key {SECRET}"},
            machine={"start": {"note": SECRET}, "end": {}},
            worktree={"before": {"status": [f"?? {SECRET}.py"]}, "after": {}},
        )

    for file in path.iterdir():
        text = file.read_text()
        assert SECRET not in text, file.name
    assert f"[redacted:{NAME}]" in (path / "output.txt").read_text()


def test_an_output_over_the_cap_is_cut_there_and_says_so(tmp_path: Path) -> None:
    assert FAILURE_OUTPUT_CAP == 5_000_000, "the default cap"

    path = _bundle(tmp_path, START, output="a" * 1000 + "tail\n", cap=100)

    text = (path / "output.txt").read_text()
    assert text.startswith("a" * 100)
    assert "tail" not in text
    assert "cut" in text.lower()
    assert len(text) < 400, "the note is short"


def test_an_output_under_the_cap_has_no_note(tmp_path: Path) -> None:
    path = _bundle(tmp_path, START, output="short\n", cap=100)

    assert (path / "output.txt").read_text() == "short\n"


def test_the_oldest_bundles_beyond_the_last_three_are_removed(tmp_path: Path) -> None:
    paths = [_bundle(tmp_path, START + timedelta(hours=n)) for n in range(RUNS_KEPT + 2)]

    assert [path.exists() for path in paths] == [False, False, True, True, True]


def test_a_bundle_a_record_points_at_is_kept_beyond_the_last_three(tmp_path: Path) -> None:
    first = _bundle(tmp_path, START)
    second = _bundle(tmp_path, START + timedelta(hours=1))
    later = [_bundle(tmp_path, START + timedelta(hours=n), pointed=[first]) for n in range(2, 6)]

    assert first.exists(), "pointed at"
    assert not second.exists()
    assert all(path.exists() for path in later[-RUNS_KEPT:])


def test_the_bundles_of_another_unit_are_left_alone(tmp_path: Path) -> None:
    other = write_failure_bundle(
        tmp_path,
        "other/2",
        "other",
        START,
        output="x",
        context={},
        machine={},
        worktree={},
    )

    for n in range(RUNS_KEPT + 1):
        _bundle(tmp_path, START + timedelta(hours=n + 1))

    assert other.exists()


# --- a failing unit-test run ------------------------------------------------------


class _Profile(PythonUvProfile):
    """The python-uv profile running one lint command and one test command."""

    def lint_command(self, base: str) -> list[str]:
        return ["lint"]

    def test_commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str]
    ) -> list[list[str]]:
        return [RUN]


class _Machine:
    """Git, lint and the test run as the processes answer; the run itself, when it is made,
    removes one file under `tests/` and adds another, as something else on the host might."""

    def __init__(self, root: Path, *, reruns: list[int], passing: bool = False) -> None:
        self.root = root
        self.reruns = list(reruns)
        self.passing = passing
        self.status_calls = 0
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.commands.append(command)
        if command == ["lint"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ["git", "status"]:
            self.status_calls += 1
            return subprocess.CompletedProcess(
                command, 0, f" M src/file{self.status_calls}.py\n", ""
            )
        if command[:2] == ["git", "rev-parse"]:
            sha = "b" * 7 if command[-1] == "main" else "a" * 7
            return subprocess.CompletedProcess(command, 0, sha + "\n", "")
        if any("::" in argument for argument in command):
            return subprocess.CompletedProcess(command, self.reruns.pop(0), "1 passed\n", "")
        if self.passing:
            return subprocess.CompletedProcess(command, 0, HEADER + "5 passed in 0.03s\n", "")
        (self.root / "tests" / "test_gone.py").unlink(missing_ok=True)
        (self.root / "tests" / "test_new.py").write_text("")
        failure = (RECORDED / "console_failures.txt").read_text().split("\n", 1)[1]
        return subprocess.CompletedProcess(command, 1, HEADER + failure, "")


@pytest.fixture
def scratch(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_gone.py").write_text("")
    (tmp_path / "tests" / "test_kept.py").write_text("")
    token = spans.current_unit.set(("add-marker/1", "add-marker", "n1", 1))
    yield tmp_path
    spans.current_unit.reset(token)


def _run(scratch: Path, machine: _Machine, directory: Path) -> tuple[bool, str] | None:
    """The unit-test run; None when it found a flake."""
    loads = iter(range(1, 100))
    clock = iter(START + timedelta(seconds=10 * n) for n in range(100))
    unit_test = build_unit_test(
        profile=cast(ToolchainProfile, _Profile()),
        run=machine,
        changed=lambda *a: ["tests/test_one.py"],
        failures_dir=directory,
        now=lambda: next(clock),
        machine=lambda: {"load": [float(next(loads))] * 3},
        tick=7,
    )
    try:
        return unit_test(cwd=scratch, base="main")
    except FlakeFound:
        return None


def _only(directory: Path) -> Path:
    found = sorted(directory.iterdir())
    assert len(found) == 1, found
    return found[0]


@pytest.mark.parametrize("reruns", [[1, 1], [0, 0]], ids=["a failure", "a flake"])
def test_a_failing_run_saves_its_whole_output(
    scratch: Path, tmp_path: Path, reruns: list[int]
) -> None:
    directory = tmp_path / "bundles"
    _run(scratch, _Machine(scratch, reruns=reruns), directory)

    bundle = _only(directory)

    assert bundle.name.startswith("add-marker-01-")
    text = (bundle / "output.txt").read_text()
    assert "short test summary info" in text
    assert "plugins: xdist-3.6.1" in text


def test_the_context_names_the_command_the_times_the_shas_and_the_versions(
    scratch: Path, tmp_path: Path
) -> None:
    directory = tmp_path / "bundles"
    _run(scratch, _Machine(scratch, reruns=[1, 1]), directory)

    context = json.loads((_only(directory) / "context.json").read_text())

    assert context["command"] == "uv run pytest -n 4 -q"
    assert context["unit"] == "add-marker/1"
    assert context["tick"] == 7
    assert context["workers"] == 4
    assert context["base"] == "b" * 7
    assert context["head"] == "a" * 7
    assert datetime.fromisoformat(context["started"]) < datetime.fromisoformat(context["ended"])
    versions = json.dumps(context["versions"])
    for version in ("3.13.1", "8.3.3", "3.6.1"):
        assert version in versions
    assert "env" not in context, "no environment variables"


def test_the_machine_is_sampled_at_the_start_and_again_at_the_end(
    scratch: Path, tmp_path: Path
) -> None:
    directory = tmp_path / "bundles"
    _run(scratch, _Machine(scratch, reruns=[1, 1]), directory)

    machine = json.loads((_only(directory) / "machine.json").read_text())

    assert machine["start"]["load"] == [1.0, 1.0, 1.0]
    assert machine["end"]["load"][0] > machine["start"]["load"][0]


def test_the_worktree_is_described_before_and_after_and_names_a_file_that_vanished(
    scratch: Path, tmp_path: Path
) -> None:
    directory = tmp_path / "bundles"
    machine = _Machine(scratch, reruns=[1, 1])
    _run(scratch, machine, directory)

    worktree = json.loads((_only(directory) / "worktree.json").read_text())

    assert worktree["before"]["status"] == [" M src/file1.py"]
    assert worktree["after"]["status"] != worktree["before"]["status"]
    assert "tests/test_gone.py" in worktree["before"]["tests"]
    assert "tests/test_gone.py" not in worktree["after"]["tests"]
    assert worktree["vanished"] == ["tests/test_gone.py"]
    assert worktree["appeared"] == ["tests/test_new.py"]


def test_a_passing_run_saves_no_bundle(scratch: Path, tmp_path: Path) -> None:
    directory = tmp_path / "bundles"
    _run(scratch, _Machine(scratch, reruns=[1, 1]), directory)
    passing = _run(scratch, _Machine(scratch, reruns=[], passing=True), directory)

    assert passing == (True, "")
    _only(directory)
