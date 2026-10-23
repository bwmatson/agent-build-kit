"""A demoted class is one more floor holding the class at `light` (spec: class-demotion, a
demotion is a runtime override that holds a class at `light`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline import demotion_record, verdict
from agent_build_kit.pipeline.verdict import ClassHistory, ReviewTier, compute_verdict
from tests.verdict_support import green_facts

AUTO, LIGHT, FULL = ReviewTier.AUTO, ReviewTier.LIGHT, ReviewTier.FULL
PROVEN = ClassHistory(samples=40, clean=40)


def test_a_demoted_class_that_clears_every_other_floor_is_held_at_light_for_the_demotion() -> None:
    result = compute_verdict(green_facts(unit_class="docs", demoted_classes=("docs",)), PROVEN)

    assert (result.tier, result.evidence_tier) == (LIGHT, AUTO)
    assert "demot" in result.reason


def test_the_same_unit_of_a_class_not_demoted_stays_at_auto() -> None:
    result = compute_verdict(green_facts(unit_class="docs", demoted_classes=("code",)), PROVEN)

    assert result.tier is AUTO


@pytest.mark.parametrize("higher", [LIGHT, FULL])
def test_the_floor_never_lowers_a_tier_another_floor_set(higher: ReviewTier) -> None:
    result = compute_verdict(
        green_facts(unit_class="docs", demoted_classes=("docs",), classification=higher), PROVEN
    )

    assert result.tier is higher
    if higher is FULL:
        assert "demot" not in result.reason


def test_a_verdict_computed_after_a_lift_is_not_held(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    path = tmp_path / demotion_record.DEMOTIONS
    at = datetime(2026, 1, 1, tzinfo=UTC)
    demotion_record.demote(
        path, unit_class="docs", trigger="revert", unit="c/1", at=at, say=lambda message: None
    )
    held = compute_verdict(
        green_facts(unit_class="docs", demoted_classes=demotion_record.demoted_classes(path)),
        PROVEN,
    )
    demotion_record.lift(path, unit_class="docs", at=at)
    after = compute_verdict(
        green_facts(unit_class="docs", demoted_classes=demotion_record.demoted_classes(path)),
        PROVEN,
    )

    assert held.tier is LIGHT
    assert after.tier is AUTO


def test_the_verdict_function_reads_no_file(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the verdict read a file")

    monkeypatch.setattr(Path, "read_text", refuse)
    monkeypatch.setattr(Path, "open", refuse)
    monkeypatch.setattr(demotion_record, "read_demotions", refuse)
    monkeypatch.setattr(demotion_record, "demoted_classes", refuse)

    result = compute_verdict(green_facts(unit_class="docs", demoted_classes=("docs",)), PROVEN)

    assert result.tier is LIGHT
    assert not hasattr(verdict, "demotion_record")
