"""`run_replacing` leaves no step behind when the replacement it runs fails."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_build_kit.sandboxes import Coverage, SandboxPolicy, held
from tests.sandboxes.stand_in import StandInBackend


def test_a_replacement_that_fails_stops_the_waiting_step(tmp_path: Path) -> None:
    pid, ready = tmp_path / "pid", tmp_path / "ready"
    script = f"echo $$ > {pid}; : > {ready}; exec sleep 60"
    given = SandboxPolicy(write=(), read=(), hosts=(), required=Coverage.NONE)

    def replace() -> None:
        raise OSError("packed-refs is absent")

    with pytest.raises(OSError, match="absent"):
        held.run_replacing(
            StandInBackend("plain", runs_as_given=True), given, script, ready=ready, replace=replace
        )

    with pytest.raises(ProcessLookupError):
        os.kill(int(pid.read_text()), 0)
