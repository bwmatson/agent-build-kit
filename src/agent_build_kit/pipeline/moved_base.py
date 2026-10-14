"""Whether a clean move onto a moved base is checked by what it can affect, or in full."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.config import RestackCheck
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.shell import git


class MoveScope(Frozen):
    """How a moved base is checked: `scoped` over the files the move brought in, or in full
    for `reason`."""

    scoped: bool
    reason: str = ""
    incoming: list[str] = []


def scope_of(own: Sequence[str], incoming: Sequence[str], setting: RestackCheck) -> MoveScope:
    """The rule over the files the unit changes and the files the move brought in.

    Scoped unless the setting says full, the unit changed nothing of its own, or a file the
    move brought in is one the unit changes, which git merging cleanly says nothing about."""
    if setting is RestackCheck.FULL:
        return MoveScope(scoped=False, reason="global_limits.restack_check is full")
    if not own:
        return MoveScope(scoped=False, reason="the unit produced nothing of its own")
    shared = sorted(set(own) & set(incoming))
    if shared:
        return MoveScope(
            scoped=False,
            reason=f"a file the unit changes was brought in: {', '.join(shared)}",
        )
    return MoveScope(scoped=True, incoming=list(incoming))


def moved_base_scope(
    tree: Path, *, own: Sequence[str], base: str, moved_from: str, setting: RestackCheck
) -> MoveScope:
    """`scope_of` over `own`, the files the unit changes, and the files that differ between
    `moved_from`, the base the restack computed, and `base`.

    A base that cannot be diffed is not an empty move: it is full, with the failure as the
    reason."""
    if setting is RestackCheck.FULL:
        return scope_of(own, [], setting)
    if not moved_from:
        return MoveScope(scoped=False, reason="the move has no old base")
    listed = git(tree, "diff", "--name-only", moved_from, base, check=False)
    if listed.returncode != 0:
        why = next((line for line in listed.stderr.splitlines() if line.strip()), "git failed")
        return MoveScope(
            scoped=False, reason=f"the files the move brought in could not be listed: {why}"
        )
    return scope_of(own, [line for line in listed.stdout.splitlines() if line.strip()], setting)
