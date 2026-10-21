"""The class a unit belongs to, from the paths it changed (spec: review-policy, classes)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.review_classes import class_of
from tests.review_config import workspace

DOCS = ["**/*.md", "docs/**"]


def test_a_unit_whose_every_path_matches_a_class_belongs_to_it() -> None:
    config = workspace({"classes": {"docs": DOCS}})

    assert class_of(config, "app", TestTier.UNIT_TEST, ["README.md", "docs/guide.md"]) == "docs"


def test_a_unit_with_a_path_that_matches_none_belongs_to_its_repo_and_kind() -> None:
    config = workspace({"classes": {"docs": DOCS}})

    paths = ["docs/guide.md", "src/app.py"]
    assert class_of(config, "app", TestTier.UNIT_TEST, paths) == "app/unit-test"
    assert class_of(config, "platform", TestTier.E2E_TEST, paths) == "platform/e2e-test"


def test_the_first_listed_class_wins() -> None:
    forward = workspace({"classes": {"first": ["docs/**"], "second": ["docs/**", "**/*.md"]}})
    backward = workspace({"classes": {"second": ["docs/**", "**/*.md"], "first": ["docs/**"]}})

    assert class_of(forward, "app", TestTier.UNIT_TEST, ["docs/guide.md"]) == "first"
    assert class_of(backward, "app", TestTier.UNIT_TEST, ["docs/guide.md"]) == "second"


def test_a_unit_with_no_changed_path_belongs_to_its_repo_and_kind() -> None:
    config = workspace({"classes": {"docs": DOCS, "anything": ["**"]}})

    assert class_of(config, "app", TestTier.UNIT_TEST, []) == "app/unit-test"
    assert class_of(config, "app", TestTier.E2E_TEST, []) == "app/e2e-test"


def test_an_integration_test_unit_is_classed_as_a_unit_test() -> None:
    config = workspace({"classes": {"docs": DOCS}})
    paths = ["docs/guide.md", "src/app.py"]

    assert class_of(config, "app", TestTier.INTEGRATION_TEST, paths) == "app/unit-test"
    assert class_of(config, "app", TestTier.INTEGRATION_TEST, paths) == class_of(
        config, "app", TestTier.UNIT_TEST, paths
    )
    assert class_of(config, "app", TestTier.INTEGRATION_TEST, []) == "app/unit-test"
    assert class_of(config, "app", TestTier.INTEGRATION_TEST, ["README.md"]) == "docs"


def test_no_class_is_ever_named_for_the_integration_test_kind() -> None:
    config = workspace({"classes": {"docs": DOCS}})

    for kind in TestTier:
        for paths in ([], ["src/app.py"], ["README.md"]):
            assert not class_of(config, "app", kind, paths).endswith("/integration-test")


def test_a_class_name_with_a_slash_is_refused_when_the_configuration_loads() -> None:
    assert workspace({"classes": {"docs": DOCS}}).review.model_dump()["classes"]

    with pytest.raises(ValidationError) as refused:
        workspace({"classes": {"app/docs": DOCS}})

    assert "app/docs" in str(refused.value)
