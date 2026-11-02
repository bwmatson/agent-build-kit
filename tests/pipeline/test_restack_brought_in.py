"""The restack names the files the move brought in, for the restack's record (spec:
restack-points, each restack decision is recorded and summarised). Real git and the real mover,
as in the other tests of `build_restack_onto`."""

from __future__ import annotations

from functools import partial
from pathlib import Path

from agent_build_kit.pipeline.restack import resolved_move
from agent_build_kit.pipeline.wiring import build_restack_onto
from tests.factories import unit
from tests.pipeline.test_restack_onto_before_push import BASE, BRANCH, Repos, stack
from tests.pipeline.test_restack_tried import leaves_markers


def test_a_clean_move_lists_the_files_the_trunk_gained(tmp_path: Path) -> None:
    repos = Repos(tmp_path, edits_shared=False)
    store = stack(tmp_path)
    repos.advance_trunk(conflicting=False)

    restacked = build_restack_onto(store, move=partial(resolved_move, resolve=leaves_markers))(
        tree=repos.tree, branch=BRANCH, base=BASE, unit=unit()
    )

    assert restacked is not None and not restacked.conflict
    assert restacked.brought_in == ("trunk.py",)


def test_a_move_that_conflicts_lists_the_files_the_trunk_gained(tmp_path: Path) -> None:
    repos = Repos(tmp_path, edits_shared=True)
    store = stack(tmp_path)
    repos.advance_trunk(conflicting=True)

    restacked = build_restack_onto(store, move=partial(resolved_move, resolve=leaves_markers))(
        tree=repos.tree, branch=BRANCH, base=BASE, unit=unit()
    )

    assert restacked is not None and restacked.conflict
    assert restacked.brought_in == ("shared.py",)
