"""A planning root whose repo `app` names a tracker, and a stand-in served for its kind, for the
tests of what `abk doctor` and `abk status` say about trackers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from agent_build_kit import trackers
from agent_build_kit.trackers.base import Identity, Tracker
from agent_build_kit.trackers.config import TrackerSection
from agent_build_kit.trackers.local import LocalTracker
from tests.cli.e2e_hold_fakes import planning
from tests.factories import init_repo

KIND = "azure_devops"
ORGANIZATION = "example-org"
IDENTITY = "sync-account"

SECTION = f"""\
    tracker:
      kind: {KIND}
      organization: {ORGANIZATION}
      project: Example Project
      team: Example Team
      area_path: Example Project\\Area
      iteration_path: Example Project\\Iteration 1
      story_type: User Story
      token_env: TRACKER_PAT
"""
# The same section without its project.
INCOMPLETE = SECTION.replace("      project: Example Project\n", "")


class RefusedTracker(LocalTracker):
    """A tracker whose host answers that the credential is refused."""

    def identity(self) -> Identity:
        raise PermissionError("401: the credential was refused")


def planned(tmp_path: Path, app_tracker: str = "") -> Path:
    """The path of an `abk.yaml` whose repo `app` carries `app_tracker`, in a git repo."""
    config = planning(tmp_path, app_tests=app_tracker)
    init_repo(config.parent)
    return config


@contextmanager
def served(tracker: Tracker | None = None) -> Iterator[None]:
    """`tracker` (default: the stand-in, as `IDENTITY`) is what the registry builds for `KIND`."""
    stand_in = tracker or LocalTracker(who=IDENTITY)

    def factory(section: TrackerSection) -> Tracker:
        return stand_in

    trackers.register(KIND, factory)
    try:
        yield
    finally:
        trackers.unregister(KIND)
