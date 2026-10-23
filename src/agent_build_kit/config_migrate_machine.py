"""Moving the machine settings of a tracked abk.yaml into abk.local.yaml, by editing both texts
as lines (spec: config-migration). The settings come from the table in `machine_settings`."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.model import Frozen

__all__ = [
    "Conflict",
    "MachineMove",
    "MachineRequest",
    "check_move",
    "move_machine_settings",
]


class MachineRequest(Frozen):
    """What the caller decides: the git top level and the directory a repo path is resolved from
    (default the top level), the local file's text (None when there is no file) and whether the
    fine-to-commit defaults of the table move too."""

    toplevel: Path
    root: Path | None = None
    local_text: str | None = None
    include_defaults: bool = False


class Conflict(Frozen):
    """A setting left in abk.yaml, and the path abk.local.yaml already sets that stops it."""

    path: tuple[str, ...]
    local_path: tuple[str, ...]


class MachineMove(Frozen):
    """The new text of each file, the paths moved and the settings left."""

    text: str
    local_text: str | None
    moved: tuple[tuple[str, ...], ...] = ()
    conflicts: tuple[Conflict, ...] = ()


def move_machine_settings(text: str, request: MachineRequest) -> MachineMove:
    """Move each machine setting of `text` that the local file does not set to the local file."""
    raise NotImplementedError


def check_move(
    old_text: str,
    old_local: str | None,
    new_text: str,
    new_local: str | None,
    moved: tuple[tuple[str, ...], ...],
) -> None:
    """Refuse, naming the first differing key, a move whose merged configuration differs or
    whose texts differ from the old ones by more than the moved paths."""
    raise NotImplementedError
