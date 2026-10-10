"""A description is shrunk to the host's limit, least important part first.

The tier 2 output goes first (its tail kept, where measures and failed bars
print), then the follow-ups, then the output altogether; the headings and the
pass or fail line are never cut.
"""

from __future__ import annotations

from agent_build_kit.pipeline.pr_body import build_pr_body
from agent_build_kit.pipeline.tier2 import Tier2Result, build_snapshot
from tests.factories import stored_unit as unit

HEADINGS = ("## Assumptions", "## Tier 2 results", "## How this was built")


def output_of(size: int) -> str:
    """Distinct numbered lines ending in a recognisable tail, `size` characters."""
    lines: list[str] = []
    while sum(len(line) + 1 for line in lines) < size:
        lines.append(f"output line {len(lines):04d} " + "o" * 30)
    text = "\n".join(lines)[: size - 40]
    return text + "\n" + "TAIL FAILED tests/test_bar.py::test_bar".ljust(39)


def snapshot(output: str) -> str:
    return build_snapshot(
        Tier2Result(
            sha="abcdef0123",
            passed=3,
            failed=1,
            skipped=0,
            duration_seconds=1.5,
            command="uv run pytest -m local_stack",
            output=output,
        )
    )


def body_of(*, output: str, follow_ups: list[str] | None = None, limit: int | None = None) -> str:
    u = unit(tier="tier2", depends_on=())
    return build_pr_body(
        u,
        graph=[u],
        base="main",
        tier2_snapshot=snapshot(output),
        follow_ups=follow_ups,
        limit=limit,
    )


def follow_ups(count: int) -> list[str]:
    return [f"follow-up {number:02d}: " + "f" * 60 for number in range(count)]


def test_a_body_that_fits_is_the_body_built_without_a_limit() -> None:
    plain = body_of(output=output_of(500), follow_ups=follow_ups(2))

    assert body_of(output=output_of(500), follow_ups=follow_ups(2), limit=len(plain) + 1) == plain
    assert body_of(output=output_of(500), follow_ups=follow_ups(2), limit=len(plain)) == plain


def test_long_output_is_trimmed_from_its_start_keeping_its_tail() -> None:
    output = output_of(4_000)

    body = body_of(output=output, limit=4_000)

    assert len(body) <= 4_000
    assert output[-200:] in body, "the tail, where the measures and failed bars print"
    assert output[:200] not in body
    for heading in HEADINGS:
        assert heading in body
    assert "3 passed, 1 failed" in body


def test_follow_ups_are_shortened_to_whole_items_once_the_output_is_at_its_floor() -> None:
    output = output_of(200)  # already under the floor: nothing there to trim
    items = follow_ups(20)
    plain = body_of(output=output, follow_ups=items)
    limit = len(plain) - 800

    body = body_of(output=output, follow_ups=items, limit=limit)

    assert len(body) <= limit
    assert output in body
    kept = [item for item in items if f"- {item}" in body]
    assert 0 < len(kept) < 20
    assert kept == items[: len(kept)], "whole items, in order"
    assert f"and {20 - len(kept)} more" in body
    assert "## Left for later" in body


def test_the_last_resort_drops_the_output_but_keeps_the_verdict() -> None:
    output = output_of(4_000)
    bare = body_of(output="", follow_ups=None)
    limit = len(bare) + 300

    body = body_of(output=output, follow_ups=follow_ups(20), limit=limit)

    assert len(body) <= limit
    assert output[-200:] not in body
    assert "trimmed" in body.lower()
    assert "3 passed, 1 failed" in body
    for heading in HEADINGS:
        assert heading in body


def test_without_follow_ups_the_output_has_the_room_they_would_have_had() -> None:
    output = output_of(6_000)
    limit = 3_000

    body = body_of(output=output, limit=limit)

    assert len(body) <= limit
    assert len(body) > limit - 200, "the room went to the output, not left unused"
    assert output[-200:] in body


def test_without_output_the_follow_ups_have_the_room_the_output_would_have_had() -> None:
    items = follow_ups(60)
    limit = 3_000

    body = body_of(output="", follow_ups=items, limit=limit)

    kept = [item for item in items if f"- {item}" in body]
    assert len(body) <= limit
    assert kept == items[: len(kept)], "whole items, in order"
    assert len(kept) < 60
    assert len(body) + len(items[0]) > limit, "another whole item would not have fitted"
    assert f"and {60 - len(kept)} more" in body


def test_above_their_smallest_forms_the_follow_ups_get_twice_the_output() -> None:
    """Weight two against weight one: what one more stretch of room is shared as."""
    output = output_of(40_000)
    items = follow_ups(300)

    def sizes(limit: int) -> tuple[int, int]:
        body = body_of(output=output, follow_ups=items, limit=limit)
        assert len(body) <= limit
        shown = body[body.index("## Tier 2 results") : body.index("## Left for later")]
        later = body[body.index("## Left for later") : body.index("## How this was built")]
        return len(shown), len(later)

    small_output, small_later = sizes(5_000)
    large_output, large_later = sizes(13_000)

    grown_output = large_output - small_output
    grown_later = large_later - small_later
    assert grown_output > 1_000
    assert abs(grown_later - 2 * grown_output) <= 300, "within a line or two of each"


def test_the_verdict_and_headings_survive_a_limit_below_everything_else() -> None:
    body = body_of(output=output_of(4_000), follow_ups=follow_ups(20), limit=1_500)

    assert len(body) <= 1_500
    assert "3 passed, 1 failed" in body
    for heading in HEADINGS:
        assert heading in body
