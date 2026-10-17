"""The whole output of each e2e-test run is kept in a file under the state directory."""

from __future__ import annotations

import contextlib
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit.config import ProjectConfig
from agent_build_kit.pipeline.archive import archive_ready_changes
from agent_build_kit.pipeline.e2e import E2eResult
from agent_build_kit.pipeline.run_log import RUNS_KEPT, e2e_output_dir
from agent_build_kit.pipeline.wiring import E2eSession
from tests.e2e_failure_fakes import checkout
from tests.factories import stored_unit, unit
from tests.pipeline.test_archive import FakeRunner

START = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)
NAME = r"add-marker-01-\d{8}-\d{6}-.*\.log"
PADDING = "." * 6000


def _big(marker: str, summary: str) -> str:
    """Far more than the 4000 characters a result keeps, with the marker at its head."""
    return f"{marker}\n{PADDING}\n{summary}\n"


def _session(
    tmp_path: Path, run, *, uid: str = "add-marker/1", at: datetime = START, **kwargs
) -> E2eSession:
    return E2eSession(
        unit(uid, change=uid.split("/")[0], tier="e2e-test"),
        lock=tmp_path / "t2.lock",
        timeout=5,
        run=run,
        sha=lambda cwd: "abc1234",
        output_dir=e2e_output_dir(tmp_path / "state"),
        now=lambda: at,
        **kwargs,
    )


def _answering(*outputs: str, code: int = 0):
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
        out = outputs[min(len(calls), len(outputs) - 1)]
        calls.append(command)
        return subprocess.CompletedProcess(command, code, out, "")

    return run


def _files(tmp_path: Path) -> list[Path]:
    directory = e2e_output_dir(tmp_path / "state")
    return sorted(directory.iterdir()) if directory.is_dir() else []


def test_the_file_holds_every_commands_output_whole_and_the_result_names_it(
    tmp_path: Path,
) -> None:
    root = checkout(tmp_path, "api", "web")
    run = _answering(
        _big("FIRST-COMMAND", "3 passed in 1.00s"), _big("SECOND-COMMAND", "1 failed in 1.00s")
    )
    projects = [ProjectConfig(path="api"), ProjectConfig(path="web")]
    session = _session(tmp_path, run, projects=projects)

    _, snapshot = session.run(cwd=root)

    assert session.result is not None
    path = Path(session.result.output_file)
    assert path.parent == e2e_output_dir(tmp_path / "state")
    assert [f.name for f in _files(tmp_path)] == [path.name]
    text = path.read_text()
    assert text.count(PADDING) == 2
    assert text.index("FIRST-COMMAND") < text.index("SECOND-COMMAND")
    assert "3 passed in 1.00s" in text, "a passing command's output is whole too"
    assert str(path) in snapshot


def test_the_name_is_change_unit_number_and_time(tmp_path: Path) -> None:
    root = checkout(tmp_path, "api")
    session = _session(tmp_path, _answering("3 passed in 1s"))

    session.run(cwd=root)

    assert session.result is not None
    name = Path(session.result.output_file).name
    assert re.fullmatch(NAME, name)
    assert "20261011-120000" in name


def test_a_command_that_raises_leaves_the_output_of_the_one_before(tmp_path: Path) -> None:
    root = checkout(tmp_path, "api", "web")
    answers = [_big("FIRST-COMMAND", "3 passed in 1.00s")]

    def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
        if answers:
            return subprocess.CompletedProcess(command, 0, answers.pop(), "")
        raise RuntimeError("the runner died")

    projects = [ProjectConfig(path="api"), ProjectConfig(path="web")]
    session = _session(tmp_path, run, projects=projects)

    with contextlib.suppress(RuntimeError):
        session.run(cwd=root)

    (file,) = _files(tmp_path)
    assert "FIRST-COMMAND" in file.read_text()


def test_the_dev_stack_path_writes_the_scripts_output_the_same_way(tmp_path: Path) -> None:
    root = checkout(tmp_path)
    script = root / "scripts" / "dev-stack.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n")

    def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
        out = _big("DEV-STACK-TEST", "2 passed in 1.00s") if command[-1] == "test" else ""
        return subprocess.CompletedProcess(command, 0, out, "")

    session = _session(tmp_path, run)

    session.run(cwd=root)

    assert session.result is not None
    path = Path(session.result.output_file)
    assert path.parent == e2e_output_dir(tmp_path / "state")
    text = path.read_text()
    assert "DEV-STACK-TEST" in text
    assert text.count(PADDING) == 1


def test_a_change_whose_name_begins_with_the_same_letters_keeps_its_files(
    tmp_path: Path,
) -> None:
    root = checkout(tmp_path, "api")
    directory = e2e_output_dir(tmp_path / "state")
    directory.mkdir(parents=True)
    others = [
        directory / f"add-marker-01-extra-01-2026010{n}-000000-1.log" for n in range(RUNS_KEPT + 2)
    ]
    for other in others:
        other.write_text("kept\n")

    for hour in range(RUNS_KEPT + 2):
        at = START + timedelta(hours=hour)
        _session(tmp_path, _answering("1 passed in 1s"), at=at).run(cwd=root)

    assert all(other.exists() for other in others)


def test_only_the_most_recent_files_of_a_unit_remain(tmp_path: Path) -> None:
    root = checkout(tmp_path, "api")
    results: list[E2eResult] = []
    for hour in range(RUNS_KEPT + 2):
        at = START + timedelta(hours=hour)
        session = _session(tmp_path, _answering("1 passed in 1s"), at=at)
        session.run(cwd=root)
        assert session.result is not None
        results.append(session.result)

    assert [f.name for f in _files(tmp_path)] == [
        Path(r.output_file).name for r in results[-RUNS_KEPT:]
    ]


def test_archiving_a_change_removes_its_files_and_not_another_changes(tmp_path: Path) -> None:
    (tmp_path / "openspec" / "changes" / "add-marker").mkdir(parents=True)
    root = checkout(tmp_path, "api")
    for uid in ("add-marker/1", "add-marker-v2/1"):
        _session(tmp_path, _answering("1 passed in 1s"), uid=uid).run(cwd=root)
    assert len(_files(tmp_path)) == 2

    archived = archive_ready_changes(
        [stored_unit("add-marker/1", state="merged")],
        planning_repo=tmp_path,
        run=FakeRunner(),
        e2e_outputs=e2e_output_dir(tmp_path / "state"),
    )

    assert archived == ["add-marker"]
    names = [f.name for f in _files(tmp_path)]
    assert len(names) == 1
    assert names[0].startswith("add-marker-v2-01-")
