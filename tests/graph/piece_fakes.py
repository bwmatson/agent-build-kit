"""A piece of a split unit prepared over a real git repository: the superseded unit's branch is
kept under its ref and holds the commits a test lists, and the piece's branch starts at the
trunk."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from agent_build_kit.pipeline.stack_runner import RunOutcome
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import UnitState
from tests.factories import activate_with, git, stored_unit
from tests.graph.branch_fakes import OnBranch, titled, write_tasks
from tests.graph.test_build_path import build
from tests.graph.test_outside_commits_prompt import branch, land

PARENT = "add-marker/1"
PIECE = "add-marker/1-s2"
KEPT = f"refs/spec-driven/superseded/{PARENT}"


def pairs(*numbers: int) -> list[str]:
    """The subjects of a per-group pair for each group, in order (groups are titled `G<n>`)."""
    return [f"{kind}: G{number}" for number in numbers for kind in ("test", "feat")]


def piece_built(
    tmp_path: Path,
    *,
    old: Sequence[str],
    piece_groups: Collection[int],
    parent_groups: Sequence[int] = (1, 2, 3),
    files: Mapping[int, dict[str, str]] | None = None,
    split_from: bool = True,
    keep_ref: bool = True,
) -> tuple[OnBranch, RunOutcome, Path]:
    """Build the piece of `piece_groups` of a unit that held `parent_groups` and was superseded,
    its branch holding commits with the subjects `old`, each in a file of its own unless `files`
    gives the one at that index its files. Without `split_from` the unit is no piece, and
    without `keep_ref` the superseded branch's ref is not there. The repo is left on the
    piece's branch, started at the trunk."""
    activate_with(builders={"per_group_commits": True})
    write_tasks(tmp_path, "add-marker", titled(*parent_groups))
    repo = branch(tmp_path)
    for index, subject in enumerate(old):
        land(repo, subject, (files or {}).get(index, {f"old-{index}.txt": f"{subject}\n"}))
    if keep_ref:
        git(repo, "update-ref", KEPT, "HEAD")
    git(repo, "checkout", "-q", "-b", f"spec/{PIECE}", "origin/main")
    store = UnitStore(tmp_path / "units.json")
    store.import_units(
        [
            stored_unit(
                PARENT,
                groups=tuple(parent_groups),
                state=UnitState.CLOSED,
                superseded_by=(PIECE,),
            ),
            stored_unit(PIECE, groups=tuple(piece_groups), split_from=PARENT if split_from else ""),
        ]
    )
    recorder = OnBranch(store)
    outcome = build(tmp_path, recorder, unit_id=PIECE, **recorder.overrides(tmp_path))
    return recorder, outcome, repo
