"""The stand-in passes the shared contract suite for every board shape and both capability modes."""

from __future__ import annotations

import pytest

from agent_build_kit.trackers.base import Capabilities, ItemKind
from agent_build_kit.trackers.local import LocalTracker
from tests.trackers import contract


@pytest.fixture(params=[True, False], ids=["checked", "unchecked"])
def revision_check(request: pytest.FixtureRequest) -> bool:
    return request.param


@pytest.fixture(params=[True, False], ids=["typed", "untyped"])
def typed(request: pytest.FixtureRequest) -> bool:
    return request.param


@pytest.fixture(params=list(contract.LEVEL_SETS))
def levels(request: pytest.FixtureRequest) -> tuple[ItemKind, ...]:
    return contract.LEVEL_SETS[request.param]


@pytest.fixture(params=[False, True], ids=["no-epic", "epic"])
def with_epic(request: pytest.FixtureRequest) -> bool:
    return request.param


@pytest.fixture
def shape(
    revision_check: bool, typed: bool, levels: tuple[ItemKind, ...], with_epic: bool
) -> contract.Shape:
    capabilities = Capabilities(revision_check=revision_check, typed=typed)
    tracker = LocalTracker(capabilities, levels=levels)
    epic = tracker.add_epic("Epic") if with_epic else None
    return contract.shape_of(tracker, tracker.as_identity("someone-else"), levels, epic)


@pytest.mark.parametrize("scenario", list(contract.SCENARIOS))
def test_the_stand_in_passes_every_scenario(scenario: str, shape: contract.Shape) -> None:
    contract.SCENARIOS[scenario](shape)


def test_the_stand_in_refuses_a_kind_outside_its_levels() -> None:
    tracker = LocalTracker(levels=["change"])

    with pytest.raises(ValueError, match="group"):
        tracker.create("group", "Story")
