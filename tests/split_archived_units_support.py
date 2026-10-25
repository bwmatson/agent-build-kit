"""A source whose moving repo has archived and no-directory units, for the split's origin tests."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.installation import Installation
from tests.factories import new_unit
from tests.planning_split_support import load
from tests.split_remove_support import trees
from tests.split_sources import write_change, write_units

__all__ = ["archived_trees"]


def archived_trees(
    tmp_path: Path, *, dropped_edge: bool = False
) -> tuple[Path, Path, Installation]:
    """A source and a destination, the source holding for `app`: an active change `one` (one
    unit), an archive entry `old` (two units) and `gone/1`, a unit whose change has no
    directory; and for `lib`, a staying change `stays` with a merged unit. With `dropped_edge`,
    `old/2` depends on the merged `lib` unit."""
    source, destination = trees(tmp_path)
    installation = load(source)
    write_change(installation, "one", ["app"])
    write_change(installation, "old", ["app"], archived="2025-01-01")
    write_change(installation, "stays", ["lib"])
    write_units(
        installation,
        new_unit("one/1", state="merged"),
        new_unit("old/1", state="merged"),
        new_unit("old/2", state="merged", depends_on=("stays/1",) if dropped_edge else ()),
        new_unit("gone/1", repo="app", state="merged"),
        new_unit("stays/1", repo="lib", state="merged"),
    )
    return source, destination, installation
