"""The hold label coming off a pull request, as the poller reports it.

`agent-hold` arriving is a `hold` event; leaving is a `release`, from the same
snapshot diff. What the unit does with it is `events`' business.
"""

from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline.pr_poller import Poller
from tests.check_lists import cancelled_list, failed_list

HOLD = ("agent-hold",)


def pr(**overrides) -> PullRequest:
    fields: dict = {"number": 4, "head": "spec/add-marker/1", "base": "main", "state": "open"}
    return PullRequest(**{**fields, **overrides})


@pytest.fixture
def poller(tmp_path: Path):
    def build(pages: list[list[PullRequest]]) -> tuple[Poller, list[tuple[str, int]]]:
        seen: list[tuple[str, int]] = []
        queue = iter(pages)
        instance = Poller(
            repo="app",
            state_path=tmp_path / "poll.json",
            list_prs=lambda: next(queue),
            dispatch=lambda action, number, **_: seen.append((action, number)),
        )
        return instance, seen

    return build


def test_the_hold_label_coming_off_releases_the_unit(poller) -> None:
    instance, seen = poller([[pr(labels=HOLD)], [pr(labels=HOLD)], [pr()]])
    instance.poll()
    instance.poll()

    instance.poll()

    assert seen == [("release", 4)]


def test_the_hold_label_still_there_is_not_a_release(poller) -> None:
    instance, seen = poller(
        [[pr(labels=HOLD)], [pr(labels=(*HOLD, "bug"))], [pr(labels=("bug", *HOLD))]]
    )
    instance.poll()

    instance.poll()
    instance.poll()

    assert seen == []


def test_another_label_coming_off_is_not_a_release(poller) -> None:
    instance, seen = poller([[pr(labels=("bug", "in-review"))], [pr(labels=("in-review",))]])
    instance.poll()

    instance.poll()

    assert seen == []


def test_a_pr_that_never_had_the_hold_label_is_not_released(poller) -> None:
    instance, seen = poller([[pr()], [pr(labels=("bug",))], [pr()]])
    instance.poll()

    instance.poll()
    instance.poll()

    assert seen == []


def test_the_first_poll_of_a_pr_records_without_a_release(poller) -> None:
    """Only a change is an event: the first poll has no previous labels to diff
    against, and the next, with the label gone, is the removal."""
    instance, seen = poller([[pr(labels=HOLD)], [pr()]])

    instance.poll()

    assert seen == []

    instance.poll()

    assert seen == [("release", 4)]


def test_a_release_is_reported_once(poller) -> None:
    instance, seen = poller([[pr(labels=HOLD)], [pr()], [pr()], [pr()]])
    for _ in range(4):
        instance.poll()

    assert seen == [("release", 4)]


def test_a_release_deferred_by_a_build_is_reported_again_until_handled(tmp_path: Path) -> None:
    pages = iter([[pr(labels=HOLD)], [pr()], [pr()], [pr()]])
    answers = iter([False, True])
    seen: list[str] = []

    def dispatch(event: str, number: int, **kwargs) -> bool:
        seen.append(event)
        return next(answers)

    instance = Poller(
        repo="o/r",
        state_path=tmp_path / "prs.json",
        list_prs=lambda: next(pages),
        dispatch=dispatch,
    )
    for _ in range(4):
        instance.poll()

    assert seen == ["release", "release"], "reported again once, then not after it was handled"


def test_a_comment_arriving_with_the_release_is_delivered_by_the_next_poll(poller) -> None:
    """The release is the poll's one event. Recording the comment as seen with
    it would leave it never delivered: the unit would wait on words nobody has
    read."""
    commented = pr(conversation=("c1",), comment_bodies=("rename the flag",))
    instance, seen = poller([[pr(labels=HOLD)], [commented], [commented], [commented]])
    for _ in range(4):
        instance.poll()

    assert seen == [("release", 4), ("rework", 4)]


def test_a_failing_check_arriving_with_the_release_is_delivered_by_the_next_poll(poller) -> None:
    red = pr(checks=failed_list("CI"))
    instance, seen = poller([[pr(labels=HOLD)], [red], [red], [red]])
    for _ in range(4):
        instance.poll()

    assert seen == [("release", 4), ("rework", 4)]


def test_a_cancelled_check_arriving_with_the_release_is_delivered_by_the_next_poll(poller) -> None:
    cancelled = pr(checks=cancelled_list("CI"))
    instance, seen = poller([[pr(labels=HOLD)], [cancelled], [cancelled], [cancelled]])
    for _ in range(4):
        instance.poll()

    assert seen == [("rerun_checks", 4), ("release", 4), ("rerun_checks", 4)]
