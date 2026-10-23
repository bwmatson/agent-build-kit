"""A unit that is not a piece is prepared as before, and a piece prepared twice picks its pairs
once (spec: split-planning)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.graph.branch_fakes import agent_calls, subjects
from tests.graph.piece_fakes import PIECE, pairs, piece_built
from tests.graph.test_build_path import build


@pytest.mark.parametrize(
    ("split_from", "keep_ref"),
    [(False, True), (True, False)],
    ids=["no split_from", "no parent ref"],
)
def test_a_unit_that_is_not_a_piece_is_built_from_scratch(
    tmp_path: Path, split_from: bool, keep_ref: bool
) -> None:
    recorder, _, repo = piece_built(
        tmp_path, old=pairs(1, 2, 3), piece_groups=(3,), split_from=split_from, keep_ref=keep_ref
    )

    assert agent_calls(recorder.events)[:2] == ["claude:tests", "claude:impl"]
    assert subjects(repo) == pairs(3)
    assert not [line for line in recorder.logged if "reuse" in line.lower()], recorder.logged


def test_a_piece_prepared_twice_does_not_pick_its_pairs_twice(tmp_path: Path) -> None:
    recorder, _, repo = piece_built(tmp_path, old=pairs(1, 2, 3), piece_groups=(3,))

    build(tmp_path, recorder, unit_id=PIECE, **recorder.overrides(tmp_path))

    assert subjects(repo) == pairs(3)
    assert agent_calls(recorder.events) == []
    said = [line for line in recorder.logged if "reused the commits" in line]
    assert len(said) == 1, recorder.logged
