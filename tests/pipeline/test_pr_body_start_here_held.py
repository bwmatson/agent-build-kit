"""A unit held for a person carries the "Start here" section beside "Held for a person"."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.pr_body import build_pr_body
from agent_build_kit.pipeline.verdict import GateResult, VerdictFacts
from tests.factories import brief_description
from tests.factories import stored_unit as unit
from tests.pipeline.test_pr_body_why import write_change

FACTS = VerdictFacts(
    kind=TestTier.UNIT_TEST, red_first=GateResult.PASSED, unit_test=GateResult.PASSED
)
FOCUS = [("src/events.py", "a boundary another system depends on")]


def body_of(tmp_path: Path, *, open_points: str | None) -> str:
    write_change(tmp_path, why="Reviewers cannot tell where to look.")
    u = unit(description=brief_description(FOCUS))
    return build_pr_body(
        u,
        graph=[u],
        base="main",
        changes_dir=tmp_path,
        open_points=open_points,
        facts=FACTS,
        rounds=3,
    )


def test_a_held_unit_carries_both_sections_in_order(tmp_path: Path) -> None:
    body = body_of(tmp_path, open_points="the lock is not released on error")

    assert "## Start here" in body
    assert "## Held for a person" in body
    assert body.index("## Start here") < body.index("## Why") < body.index("## Held for a person")
    assert "src/events.py" in body


def test_the_section_is_the_same_for_a_held_and_an_approved_unit(tmp_path: Path) -> None:
    held = body_of(tmp_path, open_points="the lock is not released on error")
    approved = body_of(tmp_path, open_points=None)

    def section(body: str) -> str:
        return body[body.index("## Start here") : body.index("## Why")]

    assert section(held) == section(approved)
