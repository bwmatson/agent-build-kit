"""The shared contract suite passes against the GitHub issues tracker through the in-memory host,
in organization and user owner modes and for each set of levels."""

from __future__ import annotations

from typing import Literal

import pytest

from agent_build_kit.trackers.github import GithubIssues
from tests.trackers import contract
from tests.trackers.github_issue_host import IssueHost
from tests.trackers.github_support import section, tracker_on

pytestmark = pytest.mark.usefixtures("github_env")

OTHER = "other-person"
OWNER_KINDS: dict[str, Literal["Organization", "User"]] = {
    "organization": "Organization",
    "user": "User",
}
SHAPES = [(mode, key) for mode in OWNER_KINDS for key in contract.LEVEL_SETS]


@pytest.fixture(params=SHAPES, ids=[f"{mode}-{key}" for mode, key in SHAPES])
def shape(request: pytest.FixtureRequest) -> contract.Shape:
    mode, key = request.param
    levels = contract.LEVEL_SETS[key]
    host = IssueHost(owner_kind=OWNER_KINDS[mode])
    tracker = tracker_on(host, mode, levels=levels)
    competitor = GithubIssues(section(mode, levels=levels), http=host.as_identity(OTHER))
    return contract.shape_of(tracker, competitor, levels)


def test_the_tracker_passes_every_scenario(shape: contract.Shape) -> None:
    for scenario in contract.SCENARIOS.values():
        scenario(shape)
