"""A comment is recorded as seen only once a unit has taken it.

Holding a unit stops the pipeline touching it; it must not discard what a
reviewer says about it. These run the real poller into the real handlers, with
only the host (the pull requests listed, the review words fetched) stood in.
"""

from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.pr_poller import Poller, PrState
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, PLANNED, SATISFIED, UnitState
from tests.factories import stored_unit as unit

PR = 4
WORDS = "Please make this a StrEnum"


def pull(*comment_ids: str, labels: tuple[str, ...] = ()) -> PullRequest:
    return PullRequest(
        labels=labels,
        number=PR,
        head="spec/add-marker/1",
        base="main",
        state="open",
        conversation=comment_ids,
        comment_bodies=tuple(WORDS for _ in comment_ids),
    )


class Harness:
    """A poller over a list of pages, dispatching into the real handlers."""

    def __init__(self, tmp_path: Path, store: UnitStore, pages: list[PullRequest]) -> None:
        self.store = store
        self.state_path = tmp_path / "poll.json"
        self.logged: list[str] = []
        self.pages = pages
        self.polls = 0
        self.waiting_path = tmp_path / "held-waiting.json"
        self.poller = Poller(
            repo="app",
            state_path=self.state_path,
            list_prs=self._list,
            dispatch=self._dispatch,
        )

    def _dispatch(self, event: str, number: int, **kwargs) -> bool:
        """A new dispatch for every event, as `poll_all` builds one per poll."""
        handle = events.build_dispatch(
            self.store,
            restack=lambda **_: None,
            fetch_review=lambda repo, number: events.Review(lines=[WORDS]),
            waiting_path=self.waiting_path,
            log=self.logged.append,
        )
        return handle(event, number, repo="app", **kwargs)

    def _list(self) -> list[PullRequest]:
        page = self.pages[min(self.polls, len(self.pages) - 1)]
        self.polls += 1
        return [page]

    def poll(self) -> None:
        self.poller.poll()

    def seen(self) -> list[str]:
        return PrState.load(self.state_path)[str(PR)]["comment_ids"]


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("add-marker/1")])
    store.set_state("add-marker/1", IN_REVIEW, pr=PR, branch="spec/add-marker/1")
    return store


def test_a_comment_on_a_held_unit_is_left_unseen(tmp_path: Path, store: UnitStore) -> None:
    harness = Harness(tmp_path, store, [pull(), pull("c1")])
    harness.poll()
    store.set_state("add-marker/1", HELD)

    harness.poll()

    assert store.get("add-marker/1").state == HELD
    assert store.get("add-marker/1").feedback == ""
    assert harness.seen() == [], "the previous snapshot is kept, so it is still new"


def test_a_released_unit_is_given_the_comment_left_while_held(
    tmp_path: Path, store: UnitStore
) -> None:
    harness = Harness(tmp_path, store, [pull(), pull("c1")])
    harness.poll()
    store.set_state("add-marker/1", HELD)
    harness.poll()

    store.set_state("add-marker/1", IN_REVIEW)
    harness.poll()

    stored = store.get("add-marker/1")
    assert stored.state == PLANNED
    assert WORDS in stored.feedback
    assert harness.seen() == ["c1"]


def test_a_comment_arriving_with_the_hold_is_delivered_on_release(
    tmp_path: Path, store: UnitStore
) -> None:
    held_with_comment = pull("c1", labels=("agent-hold",))
    harness = Harness(tmp_path, store, [pull(), held_with_comment])
    harness.poll()

    harness.poll()

    assert store.get("add-marker/1").state == HELD
    assert harness.seen() == [], "the hold does not deliver the comment, so it stays new"

    store.set_state("add-marker/1", IN_REVIEW)
    harness.poll()

    stored = store.get("add-marker/1")
    assert stored.state == PLANNED
    assert WORDS in stored.feedback
    assert harness.seen() == ["c1"]


@pytest.mark.parametrize("state", [SATISFIED, None])
def test_a_comment_no_unit_can_work_on_is_consumed(
    tmp_path: Path, store: UnitStore, state: UnitState | None
) -> None:
    """A satisfied unit's pull request is closing, and one with no unit has
    nothing to rework: neither will ever take the comment."""
    if state is None:
        store.set_state("add-marker/1", IN_REVIEW, pr=PR + 1)
    else:
        store.set_state("add-marker/1", state)
    harness = Harness(tmp_path, store, [pull(), pull("c1")])
    harness.poll()

    harness.poll()

    assert harness.seen() == ["c1"]
    assert store.get("add-marker/1").feedback == ""
    assert store.get("add-marker/1").state != PLANNED


def test_the_wait_is_logged_once_not_every_poll(tmp_path: Path, store: UnitStore) -> None:
    harness = Harness(tmp_path, store, [pull(), pull("c1")])
    harness.poll()
    store.set_state("add-marker/1", HELD)

    for _ in range(4):
        harness.poll()

    waiting = [line for line in harness.logged if "held, ignoring" in line]
    assert len(waiting) == 1
    assert harness.seen() == [], "and the comment really is still waiting"


def test_a_unit_held_again_after_release_says_so_again(tmp_path: Path, store: UnitStore) -> None:
    harness = Harness(tmp_path, store, [pull(), pull("c1"), pull("c1"), pull("c1", "c2")])
    harness.poll()
    store.set_state("add-marker/1", HELD)
    harness.poll()
    store.set_state("add-marker/1", IN_REVIEW)
    harness.poll()
    store.set_state("add-marker/1", HELD)

    harness.poll()

    assert len([line for line in harness.logged if "held, ignoring" in line]) == 2


def test_on_rework_reports_a_held_unit_as_not_taking_the_event(store: UnitStore) -> None:
    store.set_state("add-marker/1", HELD)

    taken = events.on_rework(
        PR, repo="app", reason="new comment", pull=pull("c1"), store=store, log=lambda m: None
    )

    assert taken is False
