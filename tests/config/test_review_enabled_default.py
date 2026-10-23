"""Per-tier sizing is on by default (spec: hold-and-split)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import WorkspaceConfig, review_ceiling
from agent_build_kit.init.scaffold import REVIEW_BLOCK
from agent_build_kit.pipeline.landing_decision import Condition, decide_landing
from agent_build_kit.pipeline.verdict import ReviewTier
from tests.landing_support import facts

DOCS = Path(__file__).resolve().parent.parent.parent / "docs"


def load(review: dict[str, object] | None = None) -> WorkspaceConfig:
    data: dict[str, object] = {"repos": {"app": {"path": "/work/app", "slug": "example/app"}}}
    if review is not None:
        data["review"] = review
    return WorkspaceConfig.model_validate(data)


def test_a_workspace_with_no_review_section_has_the_flag_on() -> None:
    assert load().review.enabled is True


@pytest.mark.parametrize(
    ("tier", "expected"),
    [(ReviewTier.AUTO, 5000), (ReviewTier.LIGHT, 2000), (ReviewTier.FULL, 750)],
)
def test_a_workspace_with_no_review_section_has_the_per_tier_ceilings(
    tier: ReviewTier, expected: int
) -> None:
    config = load()

    assert review_ceiling(config.repos["app"], config, tier) == expected


def test_the_init_template_states_the_default_as_true() -> None:
    assert "#   enabled: true" in REVIEW_BLOCK
    assert "#   enabled: false" not in REVIEW_BLOCK


def test_the_configuration_document_states_the_default_as_true() -> None:
    text = (DOCS / "configuration.md").read_text(encoding="utf-8")

    lines = text.splitlines()
    after_review = lines[lines.index("review:") + 1]
    assert after_review.startswith("  enabled: true")
    assert "enabled: false          # off: nothing is planned" not in text


def test_no_class_may_land_by_default() -> None:
    review = load().review

    decision = decide_landing(
        facts(review_enabled=review.enabled, listed_classes=tuple(review.auto_land.classes))
    )

    assert review.auto_land.classes == []
    assert (decision.may_land, decision.condition) == (False, Condition.CLASS_NOT_LISTED)


@pytest.mark.parametrize("tier", list(ReviewTier))
def test_an_explicit_false_holds_every_unit_to_the_full_ceiling(tier: ReviewTier) -> None:
    config = load({"enabled": False})

    assert review_ceiling(config.repos["app"], config, tier) == 750


def test_an_explicit_false_declines_landing_where_the_default_goes_on() -> None:
    off = load({"enabled": False}).review
    default = load().review
    listed = ("docs",)

    declined = decide_landing(facts(review_enabled=off.enabled, listed_classes=listed))
    allowed = decide_landing(facts(review_enabled=default.enabled, listed_classes=listed))

    assert (declined.may_land, declined.condition) == (False, Condition.REVIEW_DISABLED)
    assert allowed.may_land is True
