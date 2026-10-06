"""No infrastructure the pipeline records anything about."""

from __future__ import annotations

from agent_build_kit.model import Frozen


class NoneProfile(Frozen):
    name: str = "none"
    detect_markers: tuple[str, ...] = ()
    stack_versions_command: tuple[str, ...] | None = None


PROFILE = NoneProfile()
