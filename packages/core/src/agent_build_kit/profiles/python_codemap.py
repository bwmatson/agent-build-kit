"""The Python reader of a project's code map."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.codemap.graph import Reading


class PythonReader:
    suffixes: tuple[str, ...] = (".py",)

    def read(self, root: Path, sources: Sequence[str], tests: Sequence[str]) -> Reading:
        raise NotImplementedError
