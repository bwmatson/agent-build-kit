"""The snapshot says what the host said, even when the poll holds an event back.

A merge or close the poller cannot deliver yet (its unit is being built) keeps the old baseline
so the next poll reports it again; a reader of the snapshot must still see the pull request
merged or closed, which is how a running build learns its pull request is over.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline import snapshots
from agent_build_kit.pipeline.pr_poller import Poller, state_path
from agent_build_kit.pipeline.wiring import build_forge_state
from tests.conftest import make_installation
from tests.factories import unit

UNIT = unit("feature/1", change="feature", repo="app")
BRANCH = "spec/feature/1"


class Host:
    """The pull request as the host lists it, and the events the poller dispatched."""

    def __init__(self, state_dir: Path, *, defer: str) -> None:
        self.state = "open"
        self.defer = defer
        self.events: list[str] = []
        self.poller = Poller(
            repo="app",
            state_path=state_path(state_dir, "app"),
            list_prs=lambda: [
                PullRequest(number=7, head=BRANCH, base="main", state=self.state),
            ],
            dispatch=self.dispatch,
        )

    def dispatch(self, event: str, number: int, **_: object) -> bool:
        self.events.append(event)
        return event != self.defer


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    return make_installation(tmp_path / "planning").state_dir


@pytest.mark.parametrize("over", ["merged", "closed"])
def test_a_pull_request_over_whose_event_is_deferred_reads_as_over_from_the_snapshot(
    state_dir: Path, over: str
) -> None:
    host = Host(state_dir, defer=over)
    host.poller.poll()  # the first poll only records

    host.state = over
    host.poller.poll()

    assert host.events == [over]
    assert snapshots.pr(state_dir, "app", 7).value is not None
    assert snapshots.pr(state_dir, "app", 7).value.state == over  # type: ignore[union-attr]
    assert build_forge_state()(UNIT, 7) == over


@pytest.mark.parametrize("over", ["merged", "closed"])
def test_the_deferred_event_is_reported_again_by_the_next_poll(state_dir: Path, over: str) -> None:
    host = Host(state_dir, defer=over)
    host.poller.poll()
    host.state = over
    host.poller.poll()

    host.poller.poll()

    assert host.events == [over, over]
