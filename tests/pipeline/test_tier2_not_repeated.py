"""A tier 2 test is run by the tier 2 gate alone: tier 1's repeat and its serial rerun never
reach it, whatever `limits.tier1_repeat_runs` says (spec: tier2-failures).

The base run is the one further run of the untouched failures, and it is the gate's own.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

from agent_build_kit.pipeline.wiring import build_tier1
from agent_build_kit.profiles.base import ToolchainProfile
from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.conftest import make_installation
from tests.tier2_base_fakes import TIER2_COMMAND, Runs, branch, pytest_output, session

LIVE = "tests/live/test_live.py"
LIMITS = {"tier1_repeat_runs": 3, "tier2_base_runs": 1}
TIER2_TEST = "import pytest\n\n\n@pytest.mark.local_stack\ndef test_live():\n    assert True\n"


class Spy(PythonUvProfile):
    """The python profile, keeping the commands it was asked to rerun."""

    def __init__(self) -> None:
        self.reruns: list[list[str]] = []

    def serial_rerun_command(self, command: list[str], tests: list[str]) -> list[str]:
        self.reruns.append(command)
        return super().serial_rerun_command(command, tests)


def test_a_failing_tier_2_command_runs_once_on_the_units_tree(tmp_path: Path) -> None:
    make_installation(tmp_path / "planning", limits=LIMITS)
    repo, base = branch(tmp_path, {LIVE: TIER2_TEST})
    runs = Runs(repo, pytest_output(failed={f"{LIVE}::test_live": "assert 1 == 2"}))
    spy = Spy()
    gate = session(tmp_path, runs, profile=spy)

    ok, _ = gate.run(cwd=repo, base=base)

    assert not ok
    assert runs.on_unit == [TIER2_COMMAND]
    # the file is the unit's own, so nothing else was run, and nothing was rerun
    assert runs.on_base == []
    assert spy.reruns == []


def test_a_tier_2_command_is_not_among_the_commands_tier_1_repeats(tmp_path: Path) -> None:
    make_installation(tmp_path / "planning", limits=LIMITS)
    repo, base = branch(tmp_path, {LIVE: TIER2_TEST})
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "1 passed\n", "")

    spy = Spy()
    passed, _ = build_tier1(
        profile=cast(ToolchainProfile, spy), run=run, changed=lambda *a: [LIVE]
    )(cwd=repo, base=base)

    assert passed
    assert commands
    assert TIER2_COMMAND not in commands
    assert all("local_stack" not in " ".join(command) for command in commands)


def test_a_failing_tier_2_test_named_in_tier_1_output_is_not_rerun_as_tier_2(
    tmp_path: Path,
) -> None:
    make_installation(tmp_path / "planning", limits=LIMITS)
    repo, base = branch(tmp_path, {LIVE: TIER2_TEST})
    commands: list[list[str]] = []
    named = pytest_output(failed={f"{LIVE}::test_live": "assert 1 == 2"})

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        commands.append(command)
        # lint passes; every test command fails and names the tier 2 test
        return subprocess.CompletedProcess(command, 0 if len(commands) == 1 else 1, named, "")

    spy = Spy()
    passed, _ = build_tier1(
        profile=cast(ToolchainProfile, spy), run=run, changed=lambda *a: [LIVE]
    )(cwd=repo, base=base)

    assert not passed
    assert TIER2_COMMAND not in commands
    assert all("local_stack" not in " ".join(command) for command in spy.reruns)
    assert all("local_stack" not in " ".join(command) for command in commands)
