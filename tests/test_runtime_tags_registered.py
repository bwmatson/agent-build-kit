"""The runtime tags are registered and a mistyped one fails collection (spec:
e2e-runtime-tags)."""

from __future__ import annotations

import pytest

from agent_build_kit import runtimes
from agent_build_kit.runtimes import known_agents
from tests.runtime_tag_collection import collect, project_options
from tests.runtime_tags import PREFIX


def registered_names() -> list[str]:
    return [marker.split(":")[0].strip() for marker in project_options()["markers"]]


def test_the_registered_runtime_tags_are_the_registry_names_and_the_protocol_runtime() -> None:
    tags = {name for name in registered_names() if name.startswith(PREFIX)}

    assert tags == {f"{PREFIX}{name}" for name in {*runtimes.names(), known_agents.RUNTIME_NAME}}


def test_the_dev_stack_marker_is_registered() -> None:
    assert "dev_stack" in registered_names()


def test_the_default_options_turn_strict_markers_on() -> None:
    assert "--strict-markers" in project_options()["addopts"].split()


def test_a_mistyped_runtime_tag_fails_collection_naming_it(pytester: pytest.Pytester) -> None:
    result = collect(
        pytester,
        test_typo="""
import pytest


@pytest.mark.local_stack
@pytest.mark.runtime_typo
def test_drives_something():
    pass
""",
    )

    assert result.ret != 0
    result.stdout.fnmatch_lines(["*runtime_typo*"])
