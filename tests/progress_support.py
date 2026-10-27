"""A change's tasks file in a planning root and the tracking copy under its state directory."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.task_progress import mark_groups
from tests.conftest import make_installation

TASKS = """\
## 1. [platform] [unit-test] First
- [x] 1.1 Test: one
- [ ] 1.2 Do one

## 2. [platform] [unit-test] Second
- [ ] 2.1 Test: two, which mentions 1.2 in passing
- [ ] 2.10 Do two
- [ ] 12.1 Not group 1 or 2
"""


def planning(tmp_path: Path) -> Installation:
    """A separate planning repo at `<tmp>/planning` whose state directory is `<tmp>/state`."""
    return make_installation(
        tmp_path / "planning", planning=dict(state_dir=str(tmp_path / "state"))
    )


def meta_planning(tmp_path: Path) -> Installation:
    """The planning repo at `<tmp>/meta`, where graph tests keep their changes, with its state
    directory at `<tmp>/state`."""
    return make_installation(tmp_path / "meta", planning=dict(state_dir=str(tmp_path / "state")))


def repository_file(inst: Installation, change: str) -> Path:
    return inst.changes_dir / change / "tasks.md"


def copy_file(inst: Installation, change: str, name: str = "tasks.md") -> Path:
    """Where the tracking copy of one of the change's files is."""
    return inst.state_dir / "changes" / change / name


def write_repository(inst: Installation, change: str, text: str) -> Path:
    path = repository_file(inst, change)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def write_copy(inst: Installation, change: str, text: str) -> Path:
    path = copy_file(inst, change)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def tick(inst: Installation, change: str, groups: Iterable[int], *, done: bool) -> None:
    """`mark_groups` as the change gives it: an installation and a change name."""
    mark_groups(inst, change, groups, done=done)  # pyrefly: ignore


def ticked(path: Path) -> set[int]:
    """The groups with a ticked task in the file."""
    return {
        int(line.split()[2].split(".")[0])
        for line in path.read_text().splitlines()
        if line.startswith("- [x]")
    }
