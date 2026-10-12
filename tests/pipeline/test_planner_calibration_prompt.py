"""What the planning prompt tells the planner about each calibrated kind: the largest raw
estimate it may write, the figure to group up to, and the few most recent units behind the ratio.

The units are the stored ones; the prompt is read as the planner's runtime receives it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import active
from agent_build_kit.pipeline.planner import plan_round
from agent_build_kit.pipeline.unit_size import calibrations, recent_examples
from agent_build_kit.pipeline.unit_store import StoredUnit
from tests.calibration_support import (
    limits,
    new_unit,
    planner,
    project,
    sample,
    tasks_md,
)

OPENS = "Estimates are your raw figures"
CLOSES = "Changes ready to plan"
MAXIMUM = 2000


def prompt_for(units: list[StoredUnit], *, shown: bool = True) -> str:
    """The prompt a round sends for these units, with the ratios and examples a caller computes."""
    found = calibrations(units)
    n = active().limits.calibration_examples
    examples = {kind: recent_examples(units, kind, n) for kind in found} if shown else None
    captured: dict[str, str] = {}

    def answer(prompt: str) -> str:
        captured["prompt"] = prompt
        return '{"units": []}'

    plan_round(
        changes={"c": "## 1. [app] [tier1] x\n"},
        in_flight=[],
        calibrations=found,
        examples=examples,
        run_claude=answer,
    )
    return captured["prompt"]


def section_of(prompt: str) -> str:
    """The calibration section, from its opening line to the changes; empty when it is absent."""
    if OPENS not in prompt:
        return ""
    return prompt[prompt.index(OPENS) : prompt.index(CLOSES)]


def joining_of(prompt: str) -> str:
    return prompt[prompt.index("Joining:") : prompt.index("Respond with exactly")]


def landed(count: int, *, repo: str, ratio_of: tuple[int, int] = (400, 650), **kw) -> list:
    """`count` merged units of a repo's tier-1 kind, each landing at the same ratio."""
    estimate, actual = ratio_of
    return [
        sample(0, at=at, repo=repo, estimate=estimate, actual=actual, **kw) for at in range(count)
    ]


def titled(repo: str, *titles: str) -> list[StoredUnit]:
    """Merged units of a repo, the first title the oldest, each landing 60 over 400."""
    return [
        sample(0, at=at, repo=repo, estimate=400, actual=600 + at, title=title)
        for at, title in enumerate(titles, start=1)
    ]


SIX = ("Unit one", "Unit two", "Unit three", "Unit four", "Unit five", "Unit six")


def test_the_section_gives_the_largest_raw_estimate_and_the_raw_floor_for_a_listed_kind() -> None:
    limits()
    units = [
        *landed(20, repo="alpha"),  # 650/400 at 20 samples: ratio 1.51
        *landed(20, repo="beta", ratio_of=(400, 400)),
        *landed(2, repo="gamma", ratio_of=(400, 800)),
    ]

    prompt = prompt_for(units)
    section = section_of(prompt)

    assert "alpha" in section and "1.51" in section and "20 samples" in section
    assert "496" in section
    assert "264" in section
    assert "beta" not in prompt and "gamma" not in prompt


def test_examples_are_the_newest_merged_units_with_title_estimate_and_landed_lines() -> None:
    limits()
    units = [
        *titled("alpha", *SIX),
        *[u.model_copy(update={"branch": "spec/hidden-change/1"}) for u in landed(3, repo="alpha")],
    ]
    units = [u.model_copy(update={"change": "hidden-change"}) for u in units]

    prompt = prompt_for(units)
    section = section_of(prompt)

    assert '"Unit six": estimated 400, landed 606' in section
    assert section.index("Unit six") < section.index("Unit five") < section.index("Unit four")
    for left_out in ("Unit one", "Unit two", "Unit three"):
        assert left_out not in prompt
    assert "hidden-change" not in prompt
    assert "spec/" not in section
    assert prompt_for(units) == prompt


def test_a_unit_without_an_estimate_or_a_size_is_not_an_example() -> None:
    limits()
    units = [
        *titled("alpha", *SIX),
        sample(0, at=90, repo="alpha", estimate=0, actual=500, title="No estimate"),
        sample(0, at=91, repo="alpha", title="No size").model_copy(update={"actual_lines": None}),
    ]

    section = section_of(prompt_for(units))

    assert "Unit six" in section
    assert "No estimate" not in section and "No size" not in section


def test_with_no_examples_configured_the_figures_stay_and_no_unit_is_shown() -> None:
    limits(calibration_examples=0)

    section = section_of(prompt_for(titled("alpha", *SIX)))

    assert "alpha" in section and "496" in section
    assert not [title for title in SIX if title in section]


def test_a_title_is_cut_to_eighty_characters() -> None:
    limits()
    title = " ".join(f"w{n:03d}" for n in range(50))

    section = section_of(prompt_for(titled("alpha", "Unit one", "Unit two", title)))

    assert title[:79] in section
    assert title[:81] not in section


def test_the_kinds_with_the_most_samples_are_listed_and_the_rest_counted() -> None:
    limits()
    units = [u for n, name in enumerate("abcdefgh") for u in landed(3 + n, repo=f"kind-{name}")]

    section = section_of(prompt_for(units))

    for name in "defgh":
        assert f"kind-{name}" in section
    for name in "abc":
        assert f"kind-{name}" not in section
    left_out = [line for line in section.splitlines() if "left out" in line]
    assert len(left_out) == 1 and "3" in left_out[0]


def test_a_limit_that_holds_every_kind_leaves_none_out() -> None:
    limits(calibration_kinds_listed=8)
    units = [u for n, name in enumerate("abcdefgh") for u in landed(3 + n, repo=f"kind-{name}")]

    section = section_of(prompt_for(units))

    assert all(f"kind-{name}" in section for name in "abcdefgh")
    assert "left out" not in section


def test_kinds_with_as_many_samples_are_kept_in_the_order_of_their_names() -> None:
    limits(calibration_kinds_listed=1)
    units = [*landed(4, repo="kind-b"), *landed(4, repo="kind-a")]

    section = section_of(prompt_for(units))

    assert "kind-a" in section and "kind-b" not in section


def test_the_section_stays_under_its_maximum_at_the_largest_inputs() -> None:
    limits()
    long_title = " ".join(f"w{n:03d}" for n in range(50))
    units = [
        unit
        for name in "abcdefgh"
        for unit in titled(f"repository-{name}", long_title, long_title, long_title)
        + landed(30, repo=f"repository-{name}")
    ]

    section = section_of(prompt_for(units))

    assert "repository-" in section
    assert len(section) <= MAXIMUM


def test_the_joining_text_states_the_largest_raw_estimate_beside_the_ceiling() -> None:
    limits()
    units = landed(20, repo="alpha", ratio_of=(400, 650))  # ratio 1.5

    joining = joining_of(prompt_for(units))

    assert "750" in joining and "500" in joining
    assert joining_of(prompt_for([])) != joining


def test_with_calibration_off_the_prompt_is_the_one_without_any_calibration() -> None:
    limits()
    units = [*titled("alpha", *SIX), *landed(20, repo="alpha")]
    assert "496" in prompt_for(units)

    limits(calibrate_estimates=False)

    assert prompt_for(units) == prompt_for([])


def test_with_calibration_off_the_join_text_is_as_it_was() -> None:
    limits()
    units = landed(20, repo="alpha", ratio_of=(400, 650))
    assert "500" in joining_of(prompt_for(units))

    limits(calibrate_estimates=False)

    assert joining_of(prompt_for(units)) == joining_of(prompt_for([]))


def test_a_round_gives_the_planner_the_three_newest_units_of_each_kind_from_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    limits()
    inst, store = project(tmp_path, tasks_md(""), titled("app", *SIX))
    runtime = planner(monkeypatch, {"units": [new_unit("feature/1", [1], 100)]})

    cli.plan_all(inst, store=store)

    prompt = runtime.requests[0].prompt
    assert '"Unit six": estimated 400, landed 606' in prompt
    assert "Unit four" in prompt and "Unit three" not in prompt
