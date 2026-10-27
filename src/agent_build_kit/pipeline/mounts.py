"""Which filesystem a path is on."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.model import Frozen


class Mount(Frozen):
    fstype: str
    source: str
    options: str
    local: bool


def mount_of(path: Path, table: str | None = None) -> Mount:
    """The mount holding `path`, read from `table` (the text of `mountinfo`) or, when none is
    given, from this machine's."""
    raise NotImplementedError
