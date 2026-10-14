"""The static check never starts the agent."""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.runtimes.policy_check import check_policy
from agent_build_kit.runtimes.recommended_policy import patterns
from tests.runtimes.policy_static_support import (
    agent_home,
    entry_for,
    protocol_runtime,
    recording_program,
    write_config,
)


@pytest.fixture
def program(tmp_path: Path) -> Path:
    return recording_program(tmp_path / "bin")


def test_the_check_never_starts_the_agent(
    program: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, installation: Installation
) -> None:
    write_config(agent_home(tmp_path, monkeypatch), patterns())

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
