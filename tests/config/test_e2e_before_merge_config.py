"""`e2e_before_merge` is `required` or `deferred`: a default under `global_limits` and an optional
override on a repo's `tests` block, the repo's winning (spec: e2e-before-merge)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent_build_kit.config import (
    E2eBeforeMerge,
    LimitsConfig,
    RepoConfig,
    WorkspaceConfig,
    e2e_before_merge,
    e2e_unit_scope,
)


def workspace(limits: dict[str, Any] | None = None, **tests: Any) -> WorkspaceConfig:
    return WorkspaceConfig.model_validate(
        {
            "global_limits": limits or {},
            "repos": {
                "app": {"path": "/work/app", "slug": "example/app", "tests": tests},
                "platform": {"path": "/work/platform", "slug": "example/platform"},
            },
        }
    )


def in_effect(config: WorkspaceConfig, name: str) -> E2eBeforeMerge:
    return e2e_before_merge(config.repos[name], config.global_limits)


def test_a_file_that_does_not_mention_the_setting_requires_the_tier_for_every_repo() -> None:
    config = workspace()

    assert in_effect(config, "app") is E2eBeforeMerge.REQUIRED
    assert in_effect(config, "platform") is E2eBeforeMerge.REQUIRED


def test_a_repo_without_a_value_follows_the_global_one() -> None:
    config = workspace({"e2e_before_merge": "deferred"})

    assert in_effect(config, "app") is E2eBeforeMerge.DEFERRED
    assert in_effect(config, "platform") is E2eBeforeMerge.DEFERRED


def test_a_repo_can_defer_when_the_global_value_requires() -> None:
    config = workspace({"e2e_before_merge": "required"}, e2e_before_merge="deferred")

    assert in_effect(config, "app") is E2eBeforeMerge.DEFERRED
    assert in_effect(config, "platform") is E2eBeforeMerge.REQUIRED


def test_a_repo_can_require_when_the_global_value_defers() -> None:
    config = workspace({"e2e_before_merge": "deferred"}, e2e_before_merge="required")

    assert in_effect(config, "app") is E2eBeforeMerge.REQUIRED
    assert in_effect(config, "platform") is E2eBeforeMerge.DEFERRED


def test_the_resolver_answers_like_the_scope_one_for_a_repo_with_no_tests_block() -> None:
    repo = RepoConfig.model_validate({"path": "/work/app", "slug": "example/app"})
    limits = LimitsConfig.model_validate({"e2e_before_merge": "deferred", "e2e_unit_scope": "full"})

    assert e2e_unit_scope(repo, limits) == "full"
    assert e2e_before_merge(repo, limits) == "deferred"


@pytest.mark.parametrize("value", ["later", "Deferred", "", "off"])
def test_any_other_global_value_is_refused_naming_the_key_and_both_values(value: str) -> None:
    with pytest.raises(ValidationError, match="e2e_before_merge") as refused:
        LimitsConfig.model_validate({"e2e_before_merge": value})

    assert "Extra inputs" not in str(refused.value)
    assert "required" in str(refused.value) and "deferred" in str(refused.value)


@pytest.mark.parametrize("value", ["later", "Deferred", "", "off"])
def test_any_other_repo_value_is_refused_naming_the_key_and_both_values(value: str) -> None:
    with pytest.raises(ValidationError, match="e2e_before_merge") as refused:
        workspace(e2e_before_merge=value)

    assert "Extra inputs" not in str(refused.value)
    assert "required" in str(refused.value) and "deferred" in str(refused.value)
