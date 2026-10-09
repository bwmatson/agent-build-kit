"""The poller reads the list of checks, status by status.

A check that was pending and then fails is newly failing; a snapshot written
before the list existed holds names only and is recorded afresh, not compared.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.forges import PullRequest
from agent_build_kit.forges.base import Check, CheckStatus
from agent_build_kit.pipeline.pr_poller import Poller


def pr(*listed: tuple[str, CheckStatus], number: int = 4) -> PullRequest:
    return PullRequest(
        number=number,
        head="spec/add-marker/1",
        base="main",
        state="open",
        checks=tuple(Check(name=name, status=status) for name, status in listed),
    )


def polling(tmp_path: Path, pages: list[list[PullRequest]]) -> tuple[Poller, list[tuple]]:
    feed = iter(pages)
    last: list[PullRequest] = []

    def list_prs() -> list[PullRequest]:
        nonlocal last
        last = next(feed, last)
        return last

    seen: list[tuple] = []
    poller = Poller(
        repo="app",
        state_path=tmp_path / "poll.json",
        list_prs=list_prs,
        dispatch=lambda action, number, **kw: seen.append((action, number, kw.get("reason"))),
    )
    return poller, seen


def test_a_pending_check_that_fails_sends_the_unit_back_naming_it(tmp_path: Path) -> None:
    poller, seen = polling(
        tmp_path,
        [[pr(("CI", CheckStatus.PENDING))], [pr(("CI", CheckStatus.FAILED))]],
    )
    poller.poll()

    poller.poll()

    assert seen == [("rework", 4, "failing checks: CI")]


def test_a_pending_check_alone_sends_nothing_back(tmp_path: Path) -> None:
    poller, seen = polling(
        tmp_path,
        [[pr(("CI", CheckStatus.PASSED))], [pr(("CI", CheckStatus.PENDING))]],
    )
    poller.poll()

    poller.poll()

    assert seen == []


def test_a_check_that_was_already_failing_is_not_news(tmp_path: Path) -> None:
    failed = pr(("CI", CheckStatus.FAILED), ("lint", CheckStatus.PASSED))
    poller, seen = polling(tmp_path, [[failed], [failed]])
    poller.poll()

    poller.poll()

    assert seen == []


def test_only_the_newly_failing_checks_are_named(tmp_path: Path) -> None:
    poller, seen = polling(
        tmp_path,
        [
            [pr(("CI", CheckStatus.FAILED), ("lint", CheckStatus.PENDING))],
            [pr(("CI", CheckStatus.FAILED), ("lint", CheckStatus.FAILED))],
        ],
    )
    poller.poll()

    poller.poll()

    assert seen[-1] == ("rework", 4, "failing checks: lint")


def test_a_cancelled_check_is_rerun_as_before(tmp_path: Path) -> None:
    poller, seen = polling(
        tmp_path,
        [
            [pr(("CI", CheckStatus.PASSED))],
            [pr(("CI", CheckStatus.CANCELLED))],
            [pr(("CI", CheckStatus.FAILED))],
        ],
    )

    for _ in range(3):
        poller.poll()

    assert seen == [("rerun_checks", 4, None), ("rework", 4, "failing checks: CI")]


def test_a_cancelled_check_seen_first_is_rerun(tmp_path: Path) -> None:
    (tmp_path / "poll.json").write_text(json.dumps({}))
    poller, seen = polling(tmp_path, [[pr(("CI", CheckStatus.CANCELLED))]])

    poller.poll()

    assert seen == [("rerun_checks", 4, None)]


def test_the_snapshot_records_each_checks_name_and_status(tmp_path: Path) -> None:
    poller, _ = polling(tmp_path, [[pr(("CI", CheckStatus.PENDING), ("lint", CheckStatus.PASSED))]])

    poller.poll()

    recorded = json.loads((tmp_path / "poll.json").read_text())["4"]
    assert "failing_checks" not in recorded
    assert "cancelled_checks" not in recorded
    text = json.dumps(recorded)
    for word in ("CI", "pending", "lint", "passed"):
        assert word in text


def old_snapshot(tmp_path: Path) -> None:
    """A snapshot as written before the list: failing and cancelled names only."""
    old = {
        "state": "open",
        "last_comment": None,
        "comment_ids": [],
        "review_decision": "",
        "labels": [],
        "failing_checks": [],
        "cancelled_checks": [],
        "head": "spec/add-marker/1",
        "mergeable": True,
    }
    (tmp_path / "poll.json").write_text(json.dumps({"4": old}))


def test_an_older_snapshot_is_recorded_afresh_and_nothing_is_sent_back(tmp_path: Path) -> None:
    old_snapshot(tmp_path)
    poller, seen = polling(tmp_path, [[pr(("CI", CheckStatus.FAILED))]])

    poller.poll()

    assert seen == []
    recorded = json.loads((tmp_path / "poll.json").read_text())["4"]
    assert "failing_checks" not in recorded
    assert "CI" in json.dumps(recorded)


def test_an_older_snapshot_with_a_cancelled_check_does_not_rerun_it(tmp_path: Path) -> None:
    old_snapshot(tmp_path)
    poller, seen = polling(tmp_path, [[pr(("CI", CheckStatus.CANCELLED))]])

    poller.poll()

    assert seen == []


def test_after_being_recorded_afresh_a_later_failure_is_news(tmp_path: Path) -> None:
    old_snapshot(tmp_path)
    poller, seen = polling(
        tmp_path,
        [[pr(("CI", CheckStatus.PENDING))], [pr(("CI", CheckStatus.FAILED))]],
    )
    poller.poll()

    poller.poll()

    assert seen == [("rework", 4, "failing checks: CI")]
