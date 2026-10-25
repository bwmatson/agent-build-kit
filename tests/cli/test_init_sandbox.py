"""`abk init` runs the sandbox backend's probe when the sandbox is on, and says one line when
it is off."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from tests.cli.sandbox_cli_support import NAME, CountingBackend, switch_off, switch_on
from tests.cli.sandbox_cli_support import broken_stand_in as broken_stand_in  # noqa: F401
from tests.cli.sandbox_cli_support import stand_in as stand_in  # noqa: F401
from tests.cli.test_init import app, init_args, stubs  # noqa: F401 — fixtures
from tests.factories import recognised_planning


def rerun(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    capsys: pytest.CaptureFixture[str],
    *,
    on: bool,
    backend: str = NAME,
) -> list[str]:
    """The sandbox lines a second `abk init` prints over a kept abk.yaml."""
    planning = recognised_planning(tmp_path / "planning")
    assert main([*init_args(planning, app), "--yes"]) == 0
    if on:
        switch_on(planning / "abk.yaml", backend=backend)
    else:
        switch_off(planning / "abk.yaml")  # the sandbox is on unless the file says it is off
    capsys.readouterr()
    assert main([*init_args(planning, app), "--yes"]) == 0
    shown = capsys.readouterr()
    return [line for line in (shown.out + shown.err).splitlines() if "sandbox" in line.lower()]


def test_a_working_backend_is_reported_by_running_its_probe(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    stand_in: CountingBackend,  # noqa: F811 — fixture
    capsys: pytest.CaptureFixture[str],
) -> None:
    lines = rerun(tmp_path, app, capsys, on=True)

    assert any(stand_in.name in line for line in lines)
    assert stand_in.probes >= 1


def test_a_backend_that_does_not_work_prints_the_cause_and_the_fix(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    broken_stand_in: CountingBackend,  # noqa: F811 — fixture
    capsys: pytest.CaptureFixture[str],
) -> None:
    lines = rerun(tmp_path, app, capsys, on=True)

    text = "\n".join(lines)
    assert "stand-in off" in text
    assert "turn on" in text
    assert broken_stand_in.probes >= 1


def test_a_sandbox_that_is_off_is_one_line_and_runs_no_probe(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    stand_in: CountingBackend,  # noqa: F811 — fixture
    capsys: pytest.CaptureFixture[str],
) -> None:
    lines = rerun(tmp_path, app, capsys, on=False)

    assert len(lines) == 1
    assert " off" in lines[0]
    assert stand_in.probes == 0
