"""A plan records the sizing it was made under (spec: plan-staleness)."""

from __future__ import annotations

import pytest

from agent_build_kit import config as config_module
from agent_build_kit.cli.pipeline import plan_is_stale, sizing_digest
from agent_build_kit.config import RepoReviewConfig
from tests.factories import activate_with


def enable(**review: object) -> None:
    activate_with(review=review)


def with_limits(**limits: int) -> None:
    current = config_module.active()
    updated = current.model_copy(
        update={"global_limits": current.global_limits.model_copy(update=limits)}
    )
    config_module.activate(updated, config_module.active_root())


def test_equal_configurations_give_equal_digests() -> None:
    enable(ceilings={"light": 2000})
    first = sizing_digest()
    enable(ceilings={"light": 2000})

    assert first
    assert sizing_digest() == first


@pytest.mark.parametrize(
    "review",
    [
        {"ceilings": {"auto": 6000}},
        {"ceilings": {"light": 2500}},
        {"ceilings": {"full": 900}},
    ],
)
def test_a_changed_ceiling_changes_the_digest(review: dict) -> None:
    enable()
    before = sizing_digest()
    enable(**review)

    assert sizing_digest() != before


def test_a_changed_floor_changes_the_digest() -> None:
    enable()
    before = sizing_digest()
    with_limits(min_unit_lines=300)

    assert sizing_digest() != before


def test_a_changed_max_unit_lines_changes_the_digest() -> None:
    enable()
    before = sizing_digest()
    with_limits(max_unit_lines=800)

    assert sizing_digest() != before


def test_a_repos_review_block_changes_the_digest() -> None:
    enable()
    before = sizing_digest()
    current = config_module.active()
    app = current.repos["app"].model_copy(
        update={"review": RepoReviewConfig.model_validate({"ceilings": {"light": 1500}})}
    )
    config_module.activate(
        current.model_copy(update={"repos": {**current.repos, "app": app}}),
        config_module.active_root(),
    )

    assert sizing_digest() != before


def test_a_record_with_no_digest_is_stale() -> None:
    enable()

    assert plan_is_stale({"hash": "h", "attempts": 0, "ok": True})


def test_a_record_made_under_the_current_digest_is_not_stale() -> None:
    enable()

    assert not plan_is_stale({"hash": "h", "ok": True, "sizing": sizing_digest()})


def test_a_record_made_under_another_ceiling_is_stale() -> None:
    enable(ceilings={"light": 2000})
    record = {"hash": "h", "ok": True, "sizing": sizing_digest()}
    enable(ceilings={"light": 2500})

    assert plan_is_stale(record)
