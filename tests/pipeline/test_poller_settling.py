"""The poller keeps reading the merged pull request of a settling unit (spec: merged-waits-for-ci).

It dispatches `settled` once every check is complete and `late_check` once one has failed and none
is still running, re-runs a cancelled check and waits, waits with no time limit, and never
reworks a merged pull request for a check, a conflict or a comment.
"""

from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.forges.base import Check, CheckStatus
from agent_build_kit.pipeline.pr_poller import Poller
from agent_build_kit.pipeline.units import MERGED, SETTLING
from tests.factories import stored_unit

PASSED, FAILED, PENDING, CANCELLED = (
    CheckStatus.PASSED,
    CheckStatus.FAILED,
    CheckStatus.PENDING,
    CheckStatus.CANCELLED,
)


def merged(*checks: tuple[str, CheckStatus], **overrides) -> PullRequest:
    return PullRequest(
        number=4,
        head="spec/add-marker/1",
        base="main",
        state="merged",
        checks=tuple(Check(name=name, status=status) for name, status in checks),
        **overrides,
    )


class Pages:
    def __init__(self, pages: list[PullRequest]) -> None:
        self.pages = pages
        self.calls = 0

    def __call__(self) -> list[PullRequest]:
        page = self.pages[min(self.calls, len(self.pages) - 1)]
        self.calls += 1
        return [page]


def watch(tmp_path: Path, pages: list[PullRequest], state=SETTLING) -> tuple[Poller, list[str]]:
    seen: list[str] = []
    unit = stored_unit("add-marker/1", state=state, pr=4)
    poller = Poller(
        repo="app",
        state_path=tmp_path / "poll.json",
        list_prs=Pages(pages),
        dispatch=lambda action, number, **_: seen.append(action),
        unit_of=lambda number: unit,
    )
    return poller, seen


def poll(poller: Poller, times: int = 1) -> None:
    for _ in range(times):
        poller.poll()


@pytest.mark.parametrize("checks", [(), (("lint", PASSED),), (("lint", PASSED), ("test", PASSED))])
def test_a_settling_unit_whose_checks_are_complete_is_settled(
    tmp_path: Path, checks: tuple[tuple[str, CheckStatus], ...]
) -> None:
    """A pull request with no checks, or only skipped ones, which read as passed, settles."""
    poller, seen = watch(tmp_path, [merged(*checks)])
    poll(poller)

    poll(poller)

    assert seen == ["settled"]


def test_the_wait_has_no_time_limit(tmp_path: Path) -> None:
    poller, seen = watch(tmp_path, [merged(("test", PENDING))] * 500 + [merged(("test", PASSED))])
    poll(poller, 500)
    assert seen == []

    poll(poller)

    assert seen == ["settled"]


def test_a_failed_check_is_a_late_check_only_when_none_is_still_running(tmp_path: Path) -> None:
    poller, seen = watch(
        tmp_path,
        [
            merged(("test", PENDING), ("lint", PENDING)),
            merged(("test", FAILED), ("lint", PENDING)),
            merged(("test", FAILED), ("lint", PASSED)),
        ],
    )
    poll(poller, 2)
    assert seen == []

    poll(poller)

    assert seen == ["late_check"]


def test_a_cancelled_check_is_re_run_and_waited_for(tmp_path: Path) -> None:
    poller, seen = watch(
        tmp_path,
        [
            merged(("test", PENDING)),
            merged(("test", CANCELLED)),
            merged(("test", PENDING)),
            merged(("test", PASSED)),
        ],
    )
    poll(poller, 3)
    assert seen == ["rerun_checks"]

    poll(poller)

    assert seen == ["rerun_checks", "settled"]


@pytest.mark.parametrize("state", [SETTLING, MERGED])
def test_a_merged_pull_request_is_never_reworked(tmp_path: Path, state) -> None:
    """Not for a failing check, a conflict, a change request or a comment."""
    poller, seen = watch(
        tmp_path,
        [
            merged(("test", PENDING), mergeable=True),
            merged(
                ("test", FAILED),
                mergeable=False,
                review_decision="changes_requested",
                conversation=("c1",),
                comment_bodies=("please fix",),
            ),
        ],
        state=state,
    )
    poll(poller, 2)

    assert "rework" not in seen
    assert "conflict" not in seen
    assert ("late_check" in seen) == (state == SETTLING)
