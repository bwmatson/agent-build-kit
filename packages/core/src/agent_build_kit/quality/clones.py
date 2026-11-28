"""Clones: runs of identical tokens that occur at two places in the source files."""

from collections.abc import Mapping
from pathlib import Path

from agent_build_kit.model import Frozen


class ClonePlace(Frozen):
    """Where one copy of a clone sits: a file and its first and last line."""

    path: str
    first_line: int
    last_line: int


class Clone(Frozen):
    """A run of at least the clone length that occurs at two places."""

    places: tuple[ClonePlace, ClonePlace]


def find_clones(
    root: Path, paths: list[str], added_lines: Mapping[str, set[int]], clone_tokens: int
) -> list[Clone]:
    """The clones among the files `paths` (relative to `root`) of at least `clone_tokens` tokens
    with a token on an added line (`added_lines`: path to line numbers) at either place."""
    raise NotImplementedError
