"""A build that is not stubbed makes one pair for the unit, whatever the number of groups
(spec: per-group-commits). Each case builds the same unit stubbed beside it, so the test
fails while a build is not told apart by the setting."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from agent_build_kit import profiles
from agent_build_kit.config import RepoConfig
from agent_build_kit.profiles.base import ToolchainProfile
from tests.factories import activate_with
from tests.graph.stub_loop_fakes import StubLoop, stubbed_build, with_three_groups
from tests.graph.test_build_path import build
from tests.graph.test_joined_unit_builds import tasks
from tests.graph.test_per_group_build import group_named


class WithoutStubs:
    """The Python profile, which says nothing about stubs."""

    name = "no-stubs"

    def __getattr__(self, name: str) -> Any:
        if name == "supports_stubs":
            raise AttributeError(name)
        return getattr(profiles.get("python-uv"), name)


def built(tmp_path: Path, *, setting: bool, profile: str) -> StubLoop:
    activate_with(builders={"per_group_commits": setting})
    tasks(tmp_path, "add-marker", (1, 2, 3))
    recorder = with_three_groups(tmp_path)
    overrides = recorder.overrides(tmp_path)
    overrides["repo_config"] = RepoConfig(
        path=tmp_path / "checkouts" / "app", slug="example/app", profile=profile
    )
    with profiles.registered(cast(ToolchainProfile, WithoutStubs())):
        outcome = build(tmp_path, recorder, **overrides)
    assert outcome.status == "open"
    return recorder


@pytest.mark.parametrize(
    ("setting", "profile"),
    [(False, "python-uv"), (True, "no-stubs")],
    ids=["setting off", "profile without stubs"],
)
def test_one_pair_titled_with_the_unit_and_prompts_naming_all_groups(
    tmp_path: Path, setting: bool, profile: str
) -> None:
    stubbed_build()
    stubbed = built(tmp_path / "stubbed", setting=True, profile="python-uv")
    assert len(stubbed.subjects) == 6, "the same unit, stubbed, makes a pair for each group"

    plain = built(tmp_path / "plain", setting=setting, profile=profile)

    assert plain.subjects == ["test: Register the marker", "feat: Register the marker"]
    assert [group_named(prompt) for prompt in plain.prompts[:2]] == ["1, 2, 3", "1, 2, 3"]
    assert "stub-checks" not in plain.events
