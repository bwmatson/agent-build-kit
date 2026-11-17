"""Rebuild a repository's generated files after a restack and commit the result."""

from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.config import GeneratedConfig


class GeneratedFilesFailed(RuntimeError):
    """A regenerate command exited non-zero; `output` is what it printed."""

    output: str


def regenerate(repo: Path, entries: Sequence[GeneratedConfig], *, onto: str) -> None:
    """Run each entry whose paths the unit's commits (`onto...HEAD`) touched, in its `cwd`,
    and commit what changed as one `chore:` commit. Raises `GeneratedFilesFailed`."""
    raise NotImplementedError
