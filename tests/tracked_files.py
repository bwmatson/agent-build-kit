"""Test support: the tracked files a repo-wide guard reads, left free of planning content."""

from collections.abc import Collection
from pathlib import Path

from agent_build_kit.model import Frozen

ROOT = Path(__file__).resolve().parents[1]


class PlanningDirs(Frozen):
    specs_dir: str
    state_dir: str


def planning_dirs(root: Path) -> PlanningDirs:
    raise NotImplementedError


def guarded_files(
    root: Path = ROOT,
    *,
    under: Collection[str] = (),
    names: Collection[str] = (),
    suffixes: Collection[str] | None = None,
    specs: bool = False,
) -> list[Path]:
    raise NotImplementedError
