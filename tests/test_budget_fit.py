"""The fitter: smallest forms first, shares by weight, unused room passed on."""

from __future__ import annotations

from agent_build_kit.budget import Section, fit


def section(
    key: str,
    natural: int,
    *,
    smallest: int = 5,
    weight: int = 1,
    ceiling: int | None = None,
    required: bool = False,
    sizes: dict[str, int] | None = None,
) -> Section:
    """A section that renders as its key letter repeated up to `size` times."""
    letter = key[0]

    def render(size: int) -> str:
        shown = max(0, min(size, natural))
        if sizes is not None:
            sizes[key] = shown
        return letter * shown

    return Section(
        key=key,
        render=render,
        natural=natural,
        smallest=smallest,
        weight=weight,
        ceiling=ceiling,
        required=required,
    )


def test_everything_is_rendered_in_full_when_it_fits() -> None:
    got = fit([section("a", 10), section("b", 20)], 100)
    assert got == "a" * 10 + "\n\n" + "b" * 20


def test_a_ceiling_caps_a_section_even_when_there_is_room() -> None:
    got = fit([section("a", 50, ceiling=20), section("b", 10)], 1000)
    assert got.count("a") == 20
    assert got.count("b") == 10


def test_the_result_never_exceeds_the_budget() -> None:
    for budget in (0, 1, 7, 30, 99, 200, 500):
        sections = [
            section("a", 400, required=True),
            section("b", 400, weight=2),
            section("c", 400),
        ]
        assert len(fit(sections, budget)) <= budget


def test_smallest_forms_are_reserved_before_the_rest_is_shared() -> None:
    sizes: dict[str, int] = {}
    fit(
        [
            section("a", 500, smallest=40, sizes=sizes),
            section("b", 500, smallest=40, sizes=sizes),
        ],
        100,
        separator="",
    )
    assert sizes["a"] >= 40
    assert sizes["b"] >= 40


def test_sections_are_dropped_from_the_lowest_weight_up() -> None:
    got = fit(
        [
            section("a", 100, smallest=30, weight=3),
            section("b", 100, smallest=30, weight=1),
            section("c", 100, smallest=30, weight=2),
        ],
        70,
        separator="",
    )
    assert got.count("a") >= 30
    assert got.count("c") >= 30
    assert got.count("b") == 0


def test_a_required_section_is_never_dropped_for_a_heavier_one() -> None:
    got = fit(
        [
            section("a", 100, smallest=30, weight=1, required=True),
            section("b", 100, smallest=30, weight=5),
        ],
        40,
        separator="",
    )
    assert got.count("a") >= 30
    assert got.count("b") == 0
    assert len(got) <= 40


def test_the_order_of_sections_is_kept() -> None:
    got = fit([section("a", 100), section("b", 100), section("c", 100)], 120, separator="|")
    assert got.index("a") < got.index("b") < got.index("c")


def test_weights_divide_what_is_left_above_the_smallest_forms() -> None:
    sizes: dict[str, int] = {}
    fit(
        [
            section("a", 10_000, smallest=10, weight=2, sizes=sizes),
            section("b", 10_000, smallest=10, weight=1, sizes=sizes),
        ],
        320,
        separator="",
    )
    assert (sizes["a"] - 10) == 2 * (sizes["b"] - 10)


def test_a_short_section_passes_its_unused_share_on() -> None:
    sizes: dict[str, int] = {}
    fit(
        [
            section("a", 10, smallest=5, sizes=sizes),
            section("b", 10_000, smallest=5, sizes=sizes),
        ],
        1000,
        separator="",
    )
    assert sizes["a"] == 10
    assert sizes["b"] == 990


def test_the_remainder_goes_on_to_a_section_of_equal_weight() -> None:
    both_long: dict[str, int] = {}
    one_short: dict[str, int] = {}
    fit(
        [section("a", 10_000, sizes=both_long), section("b", 10_000, sizes=both_long)],
        1000,
        separator="",
    )
    fit(
        [section("a", 50, sizes=one_short), section("b", 10_000, sizes=one_short)],
        1000,
        separator="",
    )
    share = both_long["b"]
    assert one_short["a"] == 50
    assert one_short["b"] == share + (share - 50)


def test_room_released_by_one_section_can_saturate_another() -> None:
    sizes: dict[str, int] = {}
    fit(
        [
            section("a", 20, smallest=1, sizes=sizes),
            section("b", 300, smallest=1, sizes=sizes),
            section("c", 10_000, smallest=1, sizes=sizes),
        ],
        1000,
        separator="",
    )
    assert sizes["a"] == 20
    assert sizes["b"] == 300
    assert sizes["c"] == 680


def test_fitting_twice_gives_the_same_text() -> None:
    sections = [
        section("a", 700, weight=2),
        section("b", 30),
        section("c", 900, weight=1, required=True),
    ]
    assert fit(sections, 400) == fit(sections, 400)


def test_a_marker_added_by_a_render_is_still_within_the_budget() -> None:
    def render(size: int) -> str:
        return "m" * min(size, 500) + "[cut]"

    sections = [
        Section(key="m", render=render, natural=500, smallest=5, weight=1),
        section("b", 500),
    ]
    assert len(fit(sections, 200, separator="")) <= 200


def test_required_sections_over_the_budget_are_rendered_at_their_smallest_and_cut() -> None:
    sizes: dict[str, int] = {}
    sections = [
        section("a", 500, smallest=30, required=True, sizes=sizes),
        section("b", 500, smallest=30, required=True, sizes=sizes),
    ]
    for budget in (10, 0):
        sizes.clear()
        got = fit(sections, budget)
        assert sizes["a"] >= 30
        assert sizes["b"] >= 30
        assert len(got) <= budget
