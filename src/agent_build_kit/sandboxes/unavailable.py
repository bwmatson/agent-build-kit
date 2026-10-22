"""The backend for a platform with none: it confines nothing and says why."""

from __future__ import annotations

from collections.abc import Sequence

from agent_build_kit.sandboxes.base import (
    Availability,
    Coverage,
    SandboxPolicy,
    SandboxUnavailable,
)

CAUSE = "no sandbox backend works on this machine"
FIX = "use Linux (kernel 5.13 or later with Landlock) or macOS, or set `required: none` on the repo"


class Unavailable:
    name = "unavailable"
    platform = ""

    def availability(self) -> Availability:
        return Availability(ok=False, coverage=Coverage.NONE, cause=CAUSE, fix=FIX)

    def command(self, policy: SandboxPolicy, argv: Sequence[str]) -> list[str]:
        raise SandboxUnavailable(f"{CAUSE}: {FIX}")


BACKEND = Unavailable()
