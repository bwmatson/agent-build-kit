"""The macOS backend: a Seatbelt profile generated from the policy, run through `sandbox-exec`."""

from __future__ import annotations

from collections.abc import Sequence

from agent_build_kit.sandboxes.base import Availability, SandboxPolicy

FIX = (
    "run on macOS, where `sandbox-exec` ships with the system, or set `required: none` on the repo"
)


def profile_text(policy: SandboxPolicy) -> str:
    """The Seatbelt profile for `policy`; paths are `(param "NAME")` references, never literals."""
    raise NotImplementedError


class Seatbelt:
    name = "seatbelt"
    platform = "darwin"

    def availability(self) -> Availability:
        raise NotImplementedError

    def command(self, policy: SandboxPolicy, argv: Sequence[str]) -> list[str]:
        raise NotImplementedError


BACKEND = Seatbelt()
