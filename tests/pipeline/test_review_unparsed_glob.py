"""A glob that does not parse (`abk doctor` fails it) never raises on a decision: it protects,
and it matches no class (spec: review-policy)."""

from __future__ import annotations

from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.review_classes import class_of
from agent_build_kit.pipeline.review_paths import is_protected
from tests.review_config import workspace


def test_a_protected_glob_that_does_not_parse_protects_without_raising() -> None:
    config = workspace({"protected_defaults": False, "protected_paths": ["../outside/**"]})

    assert is_protected(config, "app", "src/app.py")


def test_a_class_glob_that_does_not_parse_matches_nothing_without_raising() -> None:
    config = workspace({"classes": {"bad": ["../outside/**"], "docs": ["docs/**"]}})

    assert class_of(config, "app", TestTier.UNIT_TEST, ["docs/guide.md"]) == "docs"
    assert class_of(config, "app", TestTier.UNIT_TEST, ["src/app.py"]) == "app/unit-test"
