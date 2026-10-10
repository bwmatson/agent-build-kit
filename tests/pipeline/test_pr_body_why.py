"""The description opens with why the change exists and what the pull request does.

The Why is the proposal's `Why` text of each change the unit builds, the goal is
the "Done when" sentence of each of its groups, and both outrank the process
text when the description is fitted to a host's limit.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.pr_body import build_pr_body
from agent_build_kit.pipeline.units import Member
from tests.factories import follow_ups, output_of, snapshot
from tests.factories import stored_unit as unit

GOAL = "Done when a loopback server answers the read endpoints."
WHY_HEADING = "## Why"
DOES_HEADING = "## What this pull request does"


def write_change(
    changes: Path, change: str = "add-marker", *, why: str | None, goals: tuple[str, ...] = (GOAL,)
) -> None:
    """A change on disk: a proposal (with a Why section when `why` is given) and
    a tasks.md with one tier 1 group for each goal."""
    root = changes / change
    root.mkdir(parents=True, exist_ok=True)
    if why is not None:
        (root / "proposal.md").write_text(
            f"# Proposal\n\n## Why\n\n{why}\n\n## What Changes\n\n- Something else entirely.\n"
        )
    groups = "".join(
        f"## {number}. [app] [tier1] Group {number}\n\n{goal}\n\n"
        f"- [ ] {number}.1 Test: it.\n- [ ] {number}.2 Do it.\n\n"
        for number, goal in enumerate(goals, start=1)
    )
    (root / "tasks.md").write_text(f"# Tasks\n\nAcceptance: none — a fixture\n\n{groups}")


def body_of(
    changes: Path | None, *, groups: tuple[int, ...] = (1,), joined: tuple[Member, ...] = (), **kw
) -> str:
    u = unit(groups=groups, joined=joined)
    return build_pr_body(u, graph=[u], base="main", changes_dir=changes, **kw)


def paragraphs(count: int, size: int = 200) -> str:
    return "\n\n".join(f"Paragraph {n}: " + "w" * size for n in range(count))


def why_of(body: str) -> str:
    return body[body.index(WHY_HEADING) : body.index(DOES_HEADING)]


def test_a_short_why_opens_the_description_in_full(tmp_path: Path) -> None:
    why = "Reviewers cannot tell why it exists.\n\nThe reason lives in another repository."
    write_change(tmp_path, why=why)

    body = body_of(tmp_path)

    assert body.startswith(WHY_HEADING)
    assert why in body
    assert "Something else entirely" not in body


def test_a_long_why_is_cut_at_a_paragraph_with_an_ellipsis_and_a_pointer(tmp_path: Path) -> None:
    write_change(tmp_path, why=paragraphs(8))

    shown = why_of(body_of(tmp_path, why_ceiling=500))

    kept = [n for n in range(8) if f"Paragraph {n}: " + "w" * 200 in shown]
    assert 0 < len(kept) < 8
    assert kept == list(range(len(kept))), "whole paragraphs, from the start"
    assert f"Paragraph {len(kept)}:" not in shown, "no paragraph is cut through"
    assert "…" in shown
    assert "openspec/changes/add-marker/proposal.md" in shown
    assert len(shown) < 500 + 400, "the ceiling is the text's, the pointer is extra"


def test_a_unit_of_part_of_a_change_says_the_reason_is_the_changes(tmp_path: Path) -> None:
    write_change(tmp_path, why="The reason.", goals=(GOAL, "Done when it is archived."))

    part = body_of(tmp_path, groups=(2,))
    whole = body_of(tmp_path, groups=(1, 2))

    assert "builds part of change **add-marker**" in part
    assert "the change's reason" in part
    assert "builds part of change" not in whole


def test_a_joined_unit_shows_one_block_for_each_change(tmp_path: Path) -> None:
    write_change(tmp_path, "add-marker", why="First reason.")
    write_change(tmp_path, "other-change", why="Second reason.", goals=("Done when it lands.",))

    body = body_of(tmp_path, joined=(Member(change="other-change", groups=(1,)),))

    why = why_of(body)
    assert why.count("First reason.") == 1
    assert why.count("Second reason.") == 1
    assert why.index("First reason.") < why.index("Second reason.")
    assert "**add-marker**" in why and "**other-change**" in why


def test_no_why_section_for_an_unreadable_proposal_or_a_missing_section(tmp_path: Path) -> None:
    write_change(tmp_path / "unreadable", why=None)
    write_change(tmp_path / "no-section", why="x")
    (tmp_path / "no-section" / "add-marker" / "proposal.md").write_text("# Proposal\n\nNo Why.\n")

    for changes in (tmp_path / "missing", tmp_path / "unreadable", tmp_path / "no-section"):
        body = body_of(changes)
        assert WHY_HEADING not in body, changes
        assert "builds part of change" not in body, changes
        assert "## Assumptions" in body, changes


def test_the_goal_sits_under_a_heading_for_what_the_pull_request_does(tmp_path: Path) -> None:
    write_change(tmp_path, why="The reason.")

    body = body_of(tmp_path)

    assert DOES_HEADING in body
    assert body.index(DOES_HEADING) < body.index(GOAL) < body.index("## Assumptions")


def test_a_group_with_no_goal_shows_none_and_nothing_else_changes(tmp_path: Path) -> None:
    write_change(tmp_path, why="The reason.", goals=("",))

    body = body_of(tmp_path)

    assert "Done when" not in body
    assert "## Assumptions" in body


def test_the_order_is_why_what_stack_scope_assumptions_verification_held_later(
    tmp_path: Path,
) -> None:
    write_change(tmp_path, why="The reason.")

    body = body_of(
        tmp_path,
        open_points="a point left outstanding",
        follow_ups=["a follow-up"],
    )

    order = [
        WHY_HEADING,
        DOES_HEADING,
        "ready to merge",
        "Unit `add-marker/1`",
        "## Assumptions",
        "## Verification",
        "## Held for a person",
        "## Left for later",
        "Opened by the spec-driven pipeline",
    ]
    positions = [body.index(part) for part in order]
    assert positions == sorted(positions)


def test_how_this_was_built_is_one_line(tmp_path: Path) -> None:
    write_change(tmp_path, why="The reason.")

    lines = body_of(tmp_path).splitlines()

    built = [line for line in lines if "Tests were committed first" in line]
    assert len(built) == 1
    assert "lint" in built[0].lower()


# Pairs as a reviewer records them: the optional finding as `file:line — summary` and the
# same point again as a follow-up, in different words.
BARE_DOCS = (
    "docs/architecture.md: mention that a merge-time restack meeting a flake records it and "
    "parks the child gated, not pushed, and that the fix change's own unit treats the flake "
    "as a tier 1 failure."
)
LOCATED_DOCS = (
    "docs/architecture.md:815 — The flake paragraph describes only the unit's node calling "
    "`on_flake`. It does not mention the merge-time restack path."
)
BARE_UNRELATED = (
    "Skip the flake rerun when the tier 1 command hit the group-1 time limit (TIMED_OUT_EXIT), "
    "with a test, so a timeout can never be reported as a flake."
)
LOCATED_OTHER = (
    "src/agent_build_kit/pipeline/wiring.py:737 — `isolate` also runs on a tier 1 command "
    "that hit the command time limit."
)


def test_a_finding_recorded_twice_is_listed_once_in_its_located_form() -> None:
    body = body_of(None, follow_ups=[BARE_DOCS, BARE_UNRELATED, LOCATED_DOCS, LOCATED_OTHER])

    assert f"- {LOCATED_DOCS}" in body
    assert "mention that a merge-time restack" not in body
    assert f"- {BARE_UNRELATED}" in body, "a bare point with no located twin is kept"
    assert f"- {LOCATED_OTHER}" in body


def test_the_located_form_wins_whichever_is_recorded_first() -> None:
    body = body_of(None, follow_ups=[LOCATED_DOCS, BARE_DOCS])

    assert f"- {LOCATED_DOCS}" in body
    assert "mention that a merge-time restack" not in body


def test_a_bare_point_naming_a_file_no_finding_locates_is_kept() -> None:
    other = "docs/code-forges.md: say that a host's limit is the lowest of all."

    body = body_of(None, follow_ups=[LOCATED_DOCS, other])

    assert f"- {other}" in body


def test_a_joined_why_that_is_short_leaves_its_room_to_the_longer_one(tmp_path: Path) -> None:
    write_change(tmp_path, "add-marker", why="Short.")
    write_change(tmp_path, "other-change", why=paragraphs(6, 150), goals=("Done when it lands.",))
    joined = (Member(change="other-change", groups=(1,)),)
    full = body_of(tmp_path, joined=joined, why_ceiling=2_000)

    cut = body_of(tmp_path, joined=joined, why_ceiling=2_000, limit=len(full) - 500)

    shown = why_of(cut)
    longer = shown[shown.index("**other-change**") :]
    assert "Paragraph 5:" not in shown, "the Why was cut"
    assert len(longer) > 0.75 * len(shown), "the short Why holds no room it does not need"


def tier2_body(tmp_path: Path, *, why: str, limit: int, items: int = 40, **kw) -> str:
    write_change(tmp_path, why=why)
    u = unit(tier="tier2", depends_on=())
    return build_pr_body(
        u,
        graph=[u],
        base="main",
        tier2_snapshot=snapshot(output_of(20_000)),
        follow_ups=follow_ups(items),
        changes_dir=tmp_path,
        limit=limit,
        **kw,
    )


def test_over_the_limit_the_output_and_follow_ups_give_way_before_the_goal_and_why(
    tmp_path: Path,
) -> None:
    why = paragraphs(2, 150)

    body = tier2_body(tmp_path, why=why, limit=3_000)

    assert len(body) <= 3_000
    assert why in body
    assert GOAL in body
    assert "- follow-up 39:" not in body, "the follow-ups were reduced"
    assert "3 passed, 1 failed" in body


def test_the_why_is_cut_to_its_ceiling_however_much_room_there_is(tmp_path: Path) -> None:
    write_change(tmp_path, why=paragraphs(30))

    shown = why_of(body_of(tmp_path, why_ceiling=600, limit=60_000))

    assert "Paragraph 29:" not in shown
    assert len(shown) < 600 + 400


def test_below_the_smallest_forms_the_goal_is_kept_and_the_why_is_cut_smallest(
    tmp_path: Path,
) -> None:
    why = paragraphs(3, 300)
    limit = len(body_of(None)) + len(GOAL) + 200

    body = tier2_body(tmp_path, why=why, limit=limit)

    assert len(body) <= limit
    assert GOAL in body
    assert "Paragraph 0: " + "w" * 300 not in body, "the Why is cut before the goal is"
    assert "## Assumptions" in body


def test_a_short_why_passes_the_room_it_does_not_use_on(tmp_path: Path) -> None:
    items = follow_ups(60)

    def shown(name: str, why: str) -> int:
        body = tier2_body(tmp_path / name, why=why, limit=3_000, items=60)
        assert len(body) <= 3_000
        return sum(f"- {item}" in body for item in items)

    short = shown("short", "A short reason.")
    long = shown("long", paragraphs(6, 300))

    assert short > long, "what the short Why leaves unused goes to the others"
