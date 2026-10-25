"""The description opens with a "Start here" section: where to look, what to skip, and what
the pipeline already verified, then the review tier, all ahead of "Why"."""

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
FOCUS = [
    ("src/events.py", "a boundary another system depends on"),
    ("src/reader.py", "a behaviour change"),
]
SKIP = [("src/old_name.py", "moved with no change to its contents")]
FACTS = VerdictFacts(
    kind=TestTier.UNIT_TEST,
    red_first=GateResult.PASSED,
    unit_test=GateResult.PASSED,
    final=True,
)
TIER_REASON = "a behaviour change in one module"


def body_of(tmp_path: Path, *, focus=(), skippable=(), described=True, **kw) -> str:
    write_change(tmp_path, why="Reviewers cannot tell where to look.")
    u = unit(description=brief_description(focus, skippable) if described else None)
    return build_pr_body(
        u, graph=[u], base="main", changes_dir=tmp_path, facts=FACTS, rounds=2, **kw
    )


def start_of(body: str) -> str:
    return body[body.index(START) : body.index(WHY)]


def test_blank_places_do_not_use_up_the_cap_and_a_backtick_in_a_place_is_replaced(
    tmp_path: Path,
) -> None:
    blanks = [(" ", "ignored")] * 3
    named = [(f"src/f{n}.py", "a behaviour change") for n in range(5)]
    ticked = [("src/a`b.py", "a behaviour change")]

    section = start_of(body_of(tmp_path, focus=[*blanks, *named], skippable=ticked))

    assert "src/f4.py" in section
    assert "`src/a'b.py`" in section


def test_the_section_leads_with_the_lists_then_the_tier_then_why(tmp_path: Path) -> None:
    activate_with(review={"enabled": True})
    verdict = tier_verdict(reason=TIER_REASON)

    body = body_of(tmp_path, focus=FOCUS, skippable=SKIP, verdict=verdict)

    assert body.startswith(START)
    section = start_of(body)
    for place, reason in [*FOCUS, *SKIP]:
        assert place in section
        assert reason in section
    order = [
        section.index(FOCUS[0][0]),
        section.index(FOCUS[1][0]),
        section.index(SKIP[0][0]),
        section.index("seen to fail first"),
        section.index(TIER_REASON),
    ]
    assert order == sorted(order), "focus, skippable, verified, then the tier line"
    assert "light" in section[order[-2] :], "the tier is named with its reason"


def test_an_empty_list_is_left_out_and_the_verified_list_is_always_there(tmp_path: Path) -> None:
    activate_with(review={"enabled": False})

    only_focus = start_of(body_of(tmp_path, focus=FOCUS))
    only_skip = start_of(body_of(tmp_path, skippable=SKIP))

    assert FOCUS[0][0] in only_focus
    assert SKIP[0][0] not in only_focus
    assert SKIP[0][0] in only_skip
    assert FOCUS[0][0] not in only_skip
    assert "seen to fail first" in only_focus
    assert "seen to fail first" in only_skip


def test_the_tier_line_needs_a_verdict(tmp_path: Path) -> None:
    verdict = tier_verdict(reason=TIER_REASON)

    assert TIER_REASON not in body_of(tmp_path, focus=FOCUS)
    assert TIER_REASON in start_of(body_of(tmp_path, focus=FOCUS, verdict=verdict))


def test_a_unit_the_reviewer_did_not_describe_gets_the_verified_list_alone(tmp_path: Path) -> None:
    activate_with(review={"enabled": False})

    section = start_of(body_of(tmp_path, described=False))

    assert "seen to fail first" in section
    assert FOCUS[0][0] not in section
    assert SKIP[0][0] not in section
