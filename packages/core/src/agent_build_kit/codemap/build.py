"""Building a project's code map from its files and its profile's reader."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agent_build_kit.codemap.graph import CodeMap, CodeReader
from agent_build_kit.config import ProjectConfig


def build_graph(
    checkout: Path,
    project: ProjectConfig,
    projects: list[ProjectConfig],
    reader: CodeReader,
    is_test: Callable[[str], bool],
) -> CodeMap:
    raise NotImplementedError
