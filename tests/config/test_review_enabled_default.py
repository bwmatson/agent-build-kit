"""Per-tier sizing is on by default (spec: hold-and-split)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import WorkspaceConfig, review_ceiling
from agent_build_kit.init.scaffold import REVIEW_BLOCK
from agent_build_kit.pipeline.verdict import ReviewTier

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
    [(ReviewTier.AUTO, 5000), (ReviewTier.LIGHT, 2000)],
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

    assert "enabled: true " in text
    assert "enabled: false          # off: nothing is planned" not in text
