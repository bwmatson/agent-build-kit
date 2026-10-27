"""The description of a unit sent on over its ceiling says so, with the size and why it was not
split; one that was not carries nothing extra (spec: unsplittable-size)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.pr_body import build_pr_body
from agent_build_kit.pipeline.unit_store import StoredSplitRequest
from tests.factories import stored_unit as unit
from tests.pipeline.test_pr_body_why import write_change

REASON = "it holds one group"
LINE = (
    "Over its tier's ceiling: 1010 changed lines against 750 (full); "
    "not split because it holds one group."
)
SPLIT = StoredSplitRequest(earned="full", lines=1010, ceiling=750)


def body_of(tmp_path: Path, **overrides) -> str:
    write_change(tmp_path, why="Reviewers cannot tell where to look.")
    u = unit(**overrides)
    return build_pr_body(u, graph=[u], base="main", changes_dir=tmp_path)


def test_a_unit_sent_on_unsplit_says_its_size_the_ceiling_the_tier_and_the_reason(
    tmp_path: Path,
) -> None:
    assert LINE in body_of(tmp_path, unsplit_reason=REASON, split_request=SPLIT)


def test_a_unit_not_sent_on_unsplit_carries_no_such_line_beside_one_that_was(
    tmp_path: Path,
) -> None:
    sent_on = body_of(tmp_path, unsplit_reason=REASON, split_request=SPLIT)
    plain = body_of(tmp_path)
    once_split = body_of(tmp_path, split_request=SPLIT)

    assert LINE in sent_on
    assert "Over its tier's ceiling" not in plain
    assert "Over its tier's ceiling" not in once_split
