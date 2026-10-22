"""The backend for a platform with none: it confines nothing and says why."""

from __future__ import annotations

from collections.abc import Sequence

from agent_build_kit.sandboxes.base import Availability, SandboxPolicy


class Unavailable:
    name = "unavailable"
    platform = ""

    def availability(self) -> Availability:
        raise NotImplementedError

    def command(self, policy: SandboxPolicy, argv: Sequence[str]) -> list[str]:
        raise NotImplementedError


BACKEND = Unavailable()
