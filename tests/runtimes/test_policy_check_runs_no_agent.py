"""The static check never starts the agent."""

from __future__ import annotations

import contextlib
import stat
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.runtimes.policy_check import check_policy
from tests.runtimes.policy_static_support import (
    FIRST,
    agent_home,
    entry_for,
    protocol_runtime,
    recommended,
    write_config,
)


@pytest.fixture
def program(tmp_path: Path) -> Path:
    """A program named for the first known agent that records a start and fails."""
    programs = tmp_path / "bin"
    programs.mkdir()
    path = programs / FIRST.program
    path.write_text(f"#!/bin/sh\necho started >> {tmp_path / 'started.log'}\nexit 1\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_the_check_never_starts_the_agent(
    program: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, installation: Installation
) -> None:
    write_config(agent_home(tmp_path, monkeypatch), recommended())

    report = check_policy(protocol_runtime(), entry_for(str(program), "acp"), installation)

    assert report.ok
    assert not (tmp_path / "started.log").exists()


def test_the_runtimes_own_method_starts_nothing(
    program: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", f"{program.parent}:/usr/bin:/bin")
    runtime = protocol_runtime()
    monkeypatch.setattr(runtime, "agent_command", (str(program), "acp"))

    # What it answers is not the point; that nothing was started is.
    with contextlib.suppress(Exception):
        runtime.check_policy(tmp_path)

    assert not (tmp_path / "started.log").exists()
