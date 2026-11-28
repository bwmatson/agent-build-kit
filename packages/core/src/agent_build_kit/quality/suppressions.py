"""Suppression markers a unit adds, each needing a reason on its line."""

from collections.abc import Mapping
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.quality.added_lines import AddedFile


class Suppression(Frozen):
    """An added suppression marker that carries no reason."""

    path: str
    line: int
    marker: str


def find_suppressions(
    root: Path, files: Mapping[str, AddedFile], *, require_reason: bool = True
) -> list[Suppression]:
    """The added suppressions without a reason, read from the files under `root`."""
    raise NotImplementedError
