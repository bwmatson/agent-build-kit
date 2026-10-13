"""Whether a clean move onto a moved base is checked by what it can affect, or in full."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.config import RestackCheck
from agent_build_kit.model import Frozen


class MoveScope(Frozen):
    """How a moved base is checked: `scoped`, or in full for `reason`."""

    scoped: bool
    reason: str = ""


def scope_of(own: Sequence[str], incoming: Sequence[str], setting: RestackCheck) -> MoveScope:
    """The rule over the files the unit changes and the files the move brought in."""
    raise NotImplementedError


def moved_base_scope(tree: Path, *, base: str, moved_from: str, setting: RestackCheck) -> MoveScope:
    """`scope_of` over the unit's files against `base` and the files that differ between
    `moved_from`, the base the restack computed, and `base`."""
    raise NotImplementedError
