"""`builders.stubbed_tdd_commits`, and when a build is stubbed (spec: per-group-commits)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent_build_kit import profiles
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.profiles.base import stubbed_build
from tests.config.builders_config import load


class NoStubs:
    """A profile that declares nothing about stubs."""

    name = "no-stubs"


def setting(loaded: WorkspaceConfig) -> Any:
    return loaded.builders.model_dump()["stubbed_tdd_commits"]


@pytest.mark.parametrize("given", [True, False])
def test_a_boolean_loads_as_given(given: bool) -> None:
    assert setting(load({"stubbed_tdd_commits": given})) is given


def test_a_string_fails_loading_naming_the_setting() -> None:
    assert setting(load({"stubbed_tdd_commits": True})) is True

    with pytest.raises(ValidationError) as refused:
        load({"stubbed_tdd_commits": "yes please"})

    errors = [e for e in refused.value.errors() if e["loc"][-1] == "stubbed_tdd_commits"]
    assert errors
    assert not any(e["type"] == "extra_forbidden" for e in errors)


def test_a_build_is_stubbed_only_when_the_setting_is_on_and_the_profile_supports_stubs() -> None:
    on = load({"stubbed_tdd_commits": True}).builders
    off = load({"stubbed_tdd_commits": False}).builders

    assert stubbed_build(on, profiles.get("python-uv")) is True
    assert stubbed_build(on, profiles.get("node-npm")) is True
    assert stubbed_build(off, profiles.get("python-uv")) is False
    assert stubbed_build(on, NoStubs()) is False
    assert stubbed_build(off, NoStubs()) is False
