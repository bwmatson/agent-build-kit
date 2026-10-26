"""A sandbox backend that is a plain class, as a test double or a third platform would be.

It confines nothing; what it was asked is kept so a test can see the call.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent_build_kit.sandboxes import Availability, Coverage, SandboxPolicy


class StandInBackend:
    def __init__(
        self, name: str, platform: str = "", *, ok: bool = True, runs_as_given: bool = False
    ) -> None:
        self.name = name
        self.platform = platform
        self.ok = ok
        # Return the argv unprefixed, so a command run through it still runs.
        self.runs_as_given = runs_as_given
        self.asked: list[tuple[SandboxPolicy, list[str]]] = []

    def availability(self) -> Availability:
        if self.ok:
            return Availability(ok=True, coverage=Coverage.PROCESS)
        return Availability(ok=False, coverage=Coverage.NONE, cause="stand-in off", fix="turn on")

    def command(self, policy: SandboxPolicy, argv: Sequence[str]) -> list[str]:
        self.asked.append((policy, list(argv)))
        return list(argv) if self.runs_as_given else ["stand-in", *argv]
