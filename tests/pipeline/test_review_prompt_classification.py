"""What the review prompt says about the classification (spec: review-classification)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.wiring import build_run_review
from tests.factories import activate_with
from tests.runtimes.stand_in import StandInRuntime


def prompt(tmp_path: Path, *, enabled: bool) -> str:
    activate_with(review={"enabled": enabled})
    runtime = StandInRuntime()
    build_run_review(runtime=runtime)(cwd=tmp_path)
    return " ".join(runtime.request.prompt.split()).lower()


def test_the_prompt_names_the_three_tiers(tmp_path: Path) -> None:
    text = prompt(tmp_path, enabled=True)

    assert "classification" in text
    for tier in ("`auto`", "`light`", "`full`"):
        assert tier in text


def test_the_prompt_names_the_three_criteria(tmp_path: Path) -> None:
    text = prompt(tmp_path, enabled=True)

    assert "boundary" in text
    assert "hard to undo" in text
    assert "tests do not exercise" in text


def test_the_prompt_says_a_classification_can_only_raise_the_review(tmp_path: Path) -> None:
    text = prompt(tmp_path, enabled=True)

    assert "raise" in text
    assert "never lower" in text


def test_the_prompt_requires_drivers_above_the_planned_estimate(tmp_path: Path) -> None:
    text = prompt(tmp_path, enabled=True)

    assert '"drivers"' in text or "`drivers`" in text
    assert "planned" in text


def test_with_review_disabled_the_prompt_is_the_one_without_the_classification_text(
    tmp_path: Path,
) -> None:
    off = prompt(tmp_path, enabled=False).split(". ")
    on = prompt(tmp_path, enabled=True).split(". ")

    assert "drivers" not in " ".join(off)
    remaining = iter(on)
    assert all(sentence in remaining for sentence in off), "the unchanged prompt is kept"
    assert len(on) > len(off), "and the classification text is what review adds"
