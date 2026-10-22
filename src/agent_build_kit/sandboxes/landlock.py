"""The Linux backend: Landlock restrictions applied by the launcher to itself before it execs."""

from __future__ import annotations

from collections.abc import Sequence

from agent_build_kit.sandboxes.base import Availability, SandboxPolicy


class Landlock:
    name = "landlock"
    platform = "linux"

    def availability(self) -> Availability:
        raise NotImplementedError

    def command(self, policy: SandboxPolicy, argv: Sequence[str]) -> list[str]:
        raise NotImplementedError


BACKEND = Landlock()
