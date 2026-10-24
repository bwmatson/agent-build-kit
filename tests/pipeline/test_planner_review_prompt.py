"""What the planning prompt says about the review tier (spec: review-tier-estimate)."""

from __future__ import annotations

from agent_build_kit.pipeline.planner import plan_round
from tests.factories import activate_with


def prompt(*, enabled: bool) -> str:
    activate_with(review={"enabled": enabled})
    captured: dict[str, str] = {}

    def answer(text: str) -> str:
        captured["prompt"] = text
        return '{"units": []}'

    plan_round(changes={"c": "## 1. [app] [unit-test] x\n"}, in_flight=[], run_claude=answer)
    return captured["prompt"]


def test_the_prompt_names_the_three_tiers_and_the_reply_key() -> None:
    text = prompt(enabled=True)

    for word in ("review_tier", "`auto`", "`light`", "`full`"):
        assert word in text


def test_the_prompt_says_the_estimate_is_a_floor_for_review_and_sizes_nothing() -> None:
    text = prompt(enabled=True).lower()

    assert "floor" in text
    assert "sizes nothing" in text


def test_the_prompt_says_what_lowers_and_what_raises_the_tier() -> None:
    text = prompt(enabled=True).lower()

    assert "lower" in text
    assert "raise" in text
    assert "protected" in text
