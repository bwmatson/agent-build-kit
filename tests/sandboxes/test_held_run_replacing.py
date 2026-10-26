"""`run_replacing` leaves no step behind when the replacement it runs fails."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import pytest

from agent_build_kit.sandboxes import Availability, Coverage, SandboxPolicy, held


class Plain:
    """A backend that confines nothing."""

    name = "plain"
    platform = ""

    def availability(self) -> Availability:
        return Availability(ok=True, coverage=Coverage.NONE)

    def command(self, policy: SandboxPolicy, argv: Sequence[str]) -> list[str]:
        return list(argv)


def test_a_replacement_that_fails_stops_the_waiting_step(tmp_path: Path) -> None:
    pid, ready = tmp_path / "pid", tmp_path / "ready"
    script = f"echo $$ > {pid}; : > {ready}; exec sleep 60"
    given = SandboxPolicy(write=(), read=(), hosts=(), required=Coverage.NONE)

    def replace() -> None:
        raise OSError("packed-refs is absent")

    with pytest.raises(OSError, match="absent"):
        held.run_replacing(Plain(), given, script, ready=ready, replace=replace)

    with pytest.raises(ProcessLookupError):
        os.kill(int(pid.read_text()), 0)
