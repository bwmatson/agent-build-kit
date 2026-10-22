"""With `review.brief` false the body is the layout from before the brief; with it true the
same unit's body differs only by the "Start here" section (spec: review-brief)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.pr_body import build_pr_body
from agent_build_kit.pipeline.verdict import GateResult, VerdictFacts
from tests.factories import activate_with, brief_description, tier_verdict
from tests.factories import stored_unit as unit
from tests.pipeline.test_pr_body_why import write_change

START = "## Start here"
WHY = "## Why"
FACTS = VerdictFacts(
    kind=TestTier.UNIT_TEST,
    red_first=GateResult.PASSED,
    unit_test=GateResult.PASSED,
    final=True,
)


def body_with(tmp_path: Path, *, brief: bool) -> str:
    activate_with(review={"enabled": True, "brief": brief})
    write_change(tmp_path, why="Reviewers cannot tell where to look.")
    u = unit(
        description=brief_description(
            [("src/events.py", "a boundary another system depends on")],
            [("src/old_name.py", "moved with no change to its contents")],
        )
    )
    return build_pr_body(
        u,
        graph=[u],
        base="main",
        changes_dir=tmp_path,
        facts=FACTS,
        rounds=2,
        verdict=tier_verdict(reason="a behaviour change in one module"),
        open_points="the lock is not released",
    )


def test_with_brief_off_the_body_has_no_start_here_section_and_opens_with_why(
    tmp_path: Path,
) -> None:
    body = body_with(tmp_path, brief=False)

    assert START not in body
    assert "Review tier" not in body
    assert body.startswith(WHY)
    assert "## Held for a person" in body


def test_with_brief_on_the_same_unit_differs_only_by_the_start_here_section(
    tmp_path: Path,
) -> None:
    off = body_with(tmp_path, brief=False)
    on = body_with(tmp_path, brief=True)

    assert on.startswith(START)
    assert on[on.index(WHY) :] == off
