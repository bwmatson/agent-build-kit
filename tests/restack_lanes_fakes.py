"""What the tests of the lanes of a workspace share: units of a project, and a lane factory
that notes the lane it made for each project."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.restack_lane import RestackLane
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import ProjectKey
from tests.factories import stored_unit
from tests.restack_lane_fakes import Restacks, lane_over

WEB = ProjectKey(repo="app", project="web")
API = ProjectKey(repo="app", project="api")
DOCS = ProjectKey(repo="platform", project=".")


def unit_of(number: int, key: ProjectKey) -> StoredUnit:
    return stored_unit(f"feature/{number}", change="feature", repo=key.repo, project=key.project)


class Made:
    """A lane factory of cap 2: it keeps each lane it made, by the project it was made for.
    Its lanes are owed every unit in `owed`."""

    def __init__(self, locks: Path, restacks: Restacks) -> None:
        self.by_project: dict[ProjectKey, RestackLane] = {}
        self.owed: set[str] = set()
        self._locks, self._restacks = locks, restacks

    def __call__(self, key: ProjectKey) -> RestackLane:
        lane = lane_over(
            self._locks,
            self._restacks,
            cap=2,
            owed=lambda units: {unit.id for unit in units if unit.id in self.owed},
        )
        self.by_project[key] = lane
        return lane
