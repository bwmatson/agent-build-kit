"""The pull request description shows the reviewer's stored description.

The core changes the reviewer wrote on approval sit under the heading for what
the pull request does, after the goal and before the process text. A push made
with the rounds spent shows the last stored description; a unit with none shows
the goal alone.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.pr_body import build_pr_body
from agent_build_kit.pipeline.unit_store import Description
from tests.factories import stored_unit as unit
from tests.pipeline.test_pr_body_why import DOES_HEADING, GOAL, write_change

DESCRIPTION = Description(
    summary="Registers the marker at startup.",
    changes=(
        "The marker registry exists.",
        "Startup registers each marker.",
        "Unknown markers are refused.",
    ),
)


def body_of(changes: Path, description: Description | None, **kw) -> str:
    u = unit(description=description)
    return build_pr_body(u, graph=[u], base="main", changes_dir=changes, **kw)


def test_the_stored_core_changes_are_shown_under_what_the_pull_request_does(
    tmp_path: Path,
) -> None:
    write_change(tmp_path, why="Because.")

    body = body_of(tmp_path, DESCRIPTION)

    does = body[body.index(DOES_HEADING) : body.index("Unit `")]
    assert GOAL in does
    for change in DESCRIPTION.changes:
        assert change in does
    assert does.index(GOAL) < does.index(DESCRIPTION.changes[0])


def test_a_push_with_rounds_spent_shows_the_last_stored_description(tmp_path: Path) -> None:
    write_change(tmp_path, why="Because.")

    body = body_of(tmp_path, DESCRIPTION, open_points="- the lock is still wrong")

    assert "## Held for a person" in body
    for change in DESCRIPTION.changes:
        assert change in body


def test_with_no_stored_description_the_goal_alone_is_shown(tmp_path: Path) -> None:
    write_change(tmp_path, why="Because.")

    body = body_of(tmp_path, None)

    does = body[body.index(DOES_HEADING) : body.index("Unit `")]
    assert GOAL in does
    assert "Startup registers" not in body


def test_a_description_over_the_limit_gives_way_before_required_sections(tmp_path: Path) -> None:
    write_change(tmp_path, why="Because.")
    limit = 4_000
    huge = Description(
        summary="s" * 900, changes=tuple(f"change {n} " + "c" * 600 for n in range(12))
    )

    body = body_of(tmp_path, huge, open_points="- the lock is still wrong", limit=limit)

    assert len(body) <= limit
    assert "## Held for a person" in body
    assert "_Opened by the spec-driven pipeline." in body
    assert GOAL in body
    assert "change 0 " in body
    assert "change 6 " not in body, "no more than six changes are shown"


def test_a_tight_limit_shrinks_the_changes_to_the_first_with_a_count(tmp_path: Path) -> None:
    write_change(tmp_path, why="Because.")
    limit = 1_800  # the fixed "Start here" section takes its share of a tight limit
    huge = Description(
        summary="s" * 900, changes=tuple(f"change {n} " + "c" * 600 for n in range(12))
    )

    body = body_of(tmp_path, huge, open_points="- the lock is still wrong", limit=limit)

    assert len(body) <= limit
    assert "## Held for a person" in body
    assert "_Opened by the spec-driven pipeline." in body
    assert GOAL in body
    assert "change 0 " in body
    assert "change 1 " not in body
    assert "…and 5 more" in body
    assert "s" * 50 not in body, "the summary is the first to go"
