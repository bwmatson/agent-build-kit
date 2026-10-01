"""Watching a repo's host for the things that should wake the pipeline.

Webhooks would need a public endpoint, and nothing here is exposed, so the
runner polls (docs/architecture.md). The signals are comments, labels, merges,
closures and check results — whatever the forge reports on a `PullRequest`.
Nothing here builds a host's JSON: how a merge or a stale comment is
recognised belongs to that forge's own tests.

The property that shapes the whole module: **only act on a change.** A poll
that re-dispatches what it saw last time would rework a unit every five
minutes, burning the usage window and force-pushing over itself.
"""

import json
from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline.pr_poller import (
    Poller,
    PrState,
    snapshot,
    state_path,
    unmergeable,
)
from agent_build_kit.pipeline.units import CLOSED, MERGED


def pr(number: int = 4, **overrides) -> PullRequest:
    defaults: dict = {
        "number": number,
        "head": "spec/add-marker/1",
        "base": "main",
        "state": "open",
    }
    return PullRequest(**{**defaults, **overrides})


def said(*ids: str) -> dict:
    """A PR carrying these comment ids, which is all the poller diffs on."""
    return {"conversation": ids, "comment_bodies": tuple(f"comment {i}" for i in ids)}


class FakePrs:
    """One page of pull requests per poll, the last repeating."""

    def __init__(self, pages: list[list[PullRequest]]) -> None:
        self.pages = pages
        self.calls = 0

    def __call__(self) -> list[PullRequest]:
        page = self.pages[min(self.calls, len(self.pages) - 1)]
        self.calls += 1
        return page


@pytest.fixture
def poller(tmp_path: Path):
    def build(pages: list[list[PullRequest]], **kw) -> tuple[Poller, list[tuple[str, int]]]:
        seen: list[tuple[str, int]] = []
        instance = Poller(
            repo="app",
            state_path=tmp_path / "poll.json",
            list_prs=FakePrs(pages),
            dispatch=lambda action, pr_number, **_: seen.append((action, pr_number)),
            **kw,
        )
        return instance, seen

    return build


def test_a_first_poll_records_state_without_dispatching_everything(poller) -> None:
    """Otherwise the first run after a restart reworks every open PR at once."""
    instance, seen = poller([[pr(), pr(5, head="spec/add-marker/2")]])

    instance.poll()

    assert seen == []


def test_nothing_happens_when_nothing_changed(poller) -> None:
    instance, seen = poller([[pr()], [pr()]])
    instance.poll()

    instance.poll()

    assert seen == []


def test_prs_that_are_not_ours_are_ignored(poller) -> None:
    """A human's PR must never be reworked or force-pushed by the pipeline."""
    instance, seen = poller(
        [
            [pr(9, head="fix/manual-thing")],
            [pr(9, head="fix/manual-thing", **said("c1"))],
        ]
    )
    instance.poll()

    instance.poll()

    assert seen == []


def test_a_new_comment_asks_for_rework(poller) -> None:
    """With no request-changes state on a single account, a comment is how
    feedback arrives."""
    instance, seen = poller([[pr()], [pr(**said("c1"))]])
    instance.poll()

    instance.poll()

    assert ("rework", 4) in seen


def test_the_same_comment_twice_is_not_two_reworks(poller) -> None:
    commented = pr(**said("c1"))
    instance, seen = poller([[pr()], [commented], [commented]])
    instance.poll()
    instance.poll()

    instance.poll()

    assert len([event for event in seen if event[0] == "rework"]) == 1


def test_a_merge_moves_the_stack_along(poller) -> None:
    instance, seen = poller([[pr()], [pr(state=MERGED)]])
    instance.poll()

    instance.poll()

    assert ("merged", 4) in seen


def test_a_closed_pr_stops_the_stack_rather_than_reworking_it(poller) -> None:
    """Closed without merging is a decision, not a defect: continuing would
    rebuild work that was deliberately dropped."""
    instance, seen = poller([[pr()], [pr(state=CLOSED)]])
    instance.poll()

    instance.poll()

    assert ("closed", 4) in seen
    assert not any(action == "rework" for action, _ in seen)


def test_a_failed_check_asks_for_rework(poller) -> None:
    instance, seen = poller(
        [
            [pr()],
            [pr(failing_checks=("CI",))],
        ]
    )
    instance.poll()

    instance.poll()

    assert ("rework", 4) in seen


def test_a_passing_check_is_not_an_event(poller) -> None:
    """Green is the expected state; dispatching on it would wake the pipeline
    for every successful run."""
    instance, seen = poller([[pr()], [pr()]])
    instance.poll()

    instance.poll()

    assert seen == []


def test_the_hold_label_stops_a_stack_advancing(poller) -> None:
    instance, seen = poller([[pr()], [pr(labels=("agent-hold",))]])
    instance.poll()

    instance.poll()

    assert ("hold", 4) in seen


def test_the_rework_label_is_feedback_given_elsewhere(poller) -> None:
    instance, seen = poller([[pr()], [pr(labels=("agent-rework",))]])
    instance.poll()

    instance.poll()

    assert ("rework", 4) in seen


def test_state_survives_a_restart(poller, tmp_path: Path) -> None:
    """Each tick is a new process; in-memory state would re-dispatch
    everything every five minutes."""
    commented = pr(**said("c1"))
    first, _ = poller([[pr()]])
    first.poll()

    second, seen = poller([[commented]])
    second.poll()
    third, seen_again = poller([[commented]])
    third.poll()

    assert ("rework", 4) in seen
    assert seen_again == []


def test_a_broken_response_does_not_lose_the_state(poller, tmp_path: Path) -> None:
    """A bad poll should cost one cycle, not re-dispatch history. A forge that
    cannot answer raises — an unauthenticated host answering with a sign-in
    page must not read as "no pull requests"."""
    instance, seen = poller([[pr()]])
    instance.poll()

    def refuses() -> list[PullRequest]:
        raise ValueError("expected a list of pull requests")

    broken = Poller(
        repo="app",
        state_path=tmp_path / "poll.json",
        list_prs=refuses,
        dispatch=lambda action, pr_number, **_: seen.append((action, pr_number)),
    )
    broken.poll()

    assert seen == []
    assert PrState.load(tmp_path / "poll.json")["4"]["state"] == "open"


def test_repeated_failures_back_off(poller, tmp_path: Path) -> None:
    """Hammering a failing endpoint every five minutes achieves nothing and
    looks like abuse from the other side."""
    failures = {"n": 0}

    def broken() -> list[PullRequest]:
        failures["n"] += 1
        raise RuntimeError("could not reach the host")

    instance = Poller(
        repo="app",
        state_path=tmp_path / "poll.json",
        list_prs=broken,
        dispatch=lambda *a, **k: None,
    )

    for _ in range(5):
        instance.poll()

    assert failures["n"] < 5, "later polls should be skipped while backing off"


def test_a_repo_polled_before_with_no_prs_is_not_a_first_run(tmp_path: Path) -> None:
    """`first_run` was "we know of no PRs", not "we have never looked". A repo
    whose first spec/ PR appears after an empty poll was treated as fresh
    forever, so that PR's events were swallowed."""
    state = tmp_path / "prs.json"
    state.write_text("{}")
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, number)),
        list_prs=lambda: [pr(1, state=MERGED)],
    ).poll()

    assert seen == [("merged", 1)]


def test_a_genuinely_first_poll_still_dispatches_nothing(tmp_path: Path) -> None:
    """The guard's real purpose: a fresh state file must not read as a hundred
    simultaneous events."""
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=tmp_path / "never-polled.json",
        dispatch=lambda event, number, **k: seen.append((event, number)),
        list_prs=lambda: [pr(1, state=MERGED), pr(2, state=MERGED)],
    ).poll()

    assert seen == []


def test_a_pr_created_and_merged_between_polls_is_not_lost(tmp_path: Path) -> None:
    """A PR opened after one poll and merged before the next would be
    recorded as merged without anyone being told, and since the poller only
    reports changes, no later poll would ever report it."""
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({"9": snapshot(pr(9))}))
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, number)),
        list_prs=lambda: [pr(9), pr(14, state=MERGED)],
    ).poll()

    assert ("merged", 14) in seen


def test_a_pr_first_seen_still_open_is_only_recorded(tmp_path: Path) -> None:
    """Nothing has happened to it yet. Only a terminal state is worth
    reporting for a PR we are meeting for the first time."""
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({"9": snapshot(pr(9))}))
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, number)),
        list_prs=lambda: [pr(9), pr(14)],
    ).poll()

    assert seen == []


def test_changes_requested_asks_for_rework(tmp_path: Path) -> None:
    """The strongest signal a reviewer can give, and `comments` alone misses
    it: a review leaving `reviewDecision: CHANGES_REQUESTED` and one inline
    comment is invisible to a poller reading `gh pr list --json comments`,
    which returns issue-level comments only."""
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({"16": snapshot(pr(16))}))
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, k.get("reason", ""))),
        list_prs=lambda: [pr(16, review_decision="changes_requested")],
    ).poll()

    assert seen and seen[0][0] == "rework"
    assert "changes requested" in seen[0][1].lower()


def test_an_approval_is_not_rework(tmp_path: Path) -> None:
    """Approved is the opposite instruction. Reworking on it would rewrite a
    branch somebody just signed off."""
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({"16": snapshot(pr(16))}))
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, k)),
        list_prs=lambda: [pr(16, review_decision="")],
    ).poll()

    assert seen == []


def test_changes_requested_only_fires_once(tmp_path: Path) -> None:
    """It stays CHANGES_REQUESTED until a new review supersedes it, so a poll
    every five minutes would otherwise rework the unit all night."""
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({"16": snapshot(pr(16, review_decision="changes_requested"))}))
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, k)),
        list_prs=lambda: [pr(16, review_decision="changes_requested")],
    ).poll()

    assert seen == []


def test_the_pipeline_s_own_replies_are_not_a_new_comment(tmp_path: Path) -> None:
    """Posting its answer to a review would otherwise send the unit straight
    back for rework, in response to itself."""
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({"17": snapshot(pr(17))}))
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, number)),
        list_prs=lambda: [pr(17, **said("PRR_mine"))],
        ignore=lambda number: {"PRR_mine"},
    ).poll()

    assert seen == []


def test_a_plain_comment_after_a_review_is_still_a_new_comment(tmp_path: Path) -> None:
    """Comments were compared by "the last id", taken from a list with every
    issue comment ahead of every review — so once a PR had a review, a later
    plain comment was never last, and a reviewer's follow-up went unseen. The
    whole set is compared instead, whatever order the host lists it in."""
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({"17": snapshot(pr(17, **said("PRR_1")))}))
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, number)),
        list_prs=lambda: [pr(17, **said("PRR_1", "IC_2"))],
    ).poll()

    assert seen == [("rework", 17)]


def test_state_recorded_before_a_field_existed_still_polls(tmp_path: Path) -> None:
    """The state file is persisted data, so it outlives the shape of the code
    that wrote it. Adding `review_decision` to the snapshot made every poll
    fail with KeyError against state recorded the day before — and would do the
    same for the next field somebody adds."""
    state = tmp_path / "prs.json"
    old = {
        "state": "OPEN",
        "merged": False,
        "last_comment": None,
        "labels": [],
        "failing_checks": [],
        "head": "spec/add-marker/1",
    }
    state.write_text(json.dumps({"16": old}))
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, number)),
        list_prs=lambda: [pr(16, review_decision="changes_requested")],
    ).poll()

    assert seen == [("rework", 16)], "a field absent from the old snapshot reads as unchanged"


def test_a_pr_first_seen_with_ci_already_red_is_reworked(tmp_path: Path) -> None:
    """The pipeline opens its own PRs, so CI usually finishes after the poll
    that first sees one. A failure recorded as the starting state is never
    newly failing, and the PR sits red while the tick builds on it."""
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({}))
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, number, k.get("reason"))),
        list_prs=lambda: [pr(20, failing_checks=("config-check",))],
    ).poll()

    assert seen == [("rework", 20, "failing checks: config-check")]


def test_a_deferred_event_is_reported_again_until_it_is_handled(tmp_path: Path) -> None:
    """A handler defers an event for a unit still being built. Recording the
    change anyway would make that the only time it is ever seen."""
    held = pr(labels=("agent-hold",))
    pages = iter([[pr()], [held], [held], [held]])
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

    assert seen == ["hold", "hold"], "reported again once, then not after it was handled"


def test_a_deferred_event_on_a_pr_seen_for_the_first_time_is_kept(tmp_path: Path) -> None:
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({}))
    merged = pr(20, state=MERGED)
    answers = iter([False, True])
    seen: list[str] = []

    def dispatch(event: str, number: int, **kwargs) -> bool:
        seen.append(event)
        return next(answers)

    instance = Poller(repo="o/r", state_path=state, list_prs=lambda: [merged], dispatch=dispatch)
    for _ in range(3):
        instance.poll()

    assert seen == ["merged", "merged"]


def test_a_snapshot_written_before_the_forges_existed_dispatches_nothing(tmp_path: Path) -> None:
    """These files survive an upgrade. One written when the snapshot held
    GitHub's own words — `merged: true`, `CHANGES_REQUESTED` — must not read as
    "everything changed": every in-flight PR would be reworked once for
    nothing, and a merged one restacked a second time."""
    state = tmp_path / "prs.json"
    state.write_text(
        json.dumps(
            {
                "16": {
                    "state": "OPEN",
                    "merged": False,
                    "last_comment": "c1",
                    "comment_ids": ["c1"],
                    "review_decision": "CHANGES_REQUESTED",
                    "labels": [],
                    "failing_checks": [],
                    "head": "spec/add-marker/1",
                }
            }
        )
    )
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, number)),
        list_prs=lambda: [pr(16, review_decision="changes_requested", **said("c1"))],
    ).poll()

    assert seen == []
    assert PrState.load(state)["16"]["state"] == "open", "and it is rewritten in the new words"


def test_a_merge_recorded_in_the_old_words_is_not_reported_twice(tmp_path: Path) -> None:
    state = tmp_path / "prs.json"
    state.write_text(
        json.dumps({"16": {"state": "OPEN", "merged": True, "comment_ids": [], "labels": []}})
    )
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, number)),
        list_prs=lambda: [pr(16, state=MERGED)],
    ).poll()

    assert seen == []


@pytest.fixture
def conflicts(tmp_path: Path):
    """A poller over successive answers, recording each dispatch's reason."""

    def build(pages: list[list[PullRequest]]) -> tuple[Poller, list[tuple[str, int, str]]]:
        seen: list[tuple[str, int, str]] = []
        instance = Poller(
            repo="app",
            state_path=tmp_path / "poll.json",
            list_prs=FakePrs(pages),
            dispatch=lambda action, pr_number, **k: seen.append(
                (action, pr_number, k.get("reason", ""))
            ),
        )
        return instance, seen

    return build


def test_mergeability_is_kept_in_the_snapshot() -> None:
    assert snapshot(pr(mergeable=False))["mergeable"] is False
    assert snapshot(pr(mergeable=True))["mergeable"] is True
    assert snapshot(pr())["mergeable"] is None


def test_a_branch_that_stops_merging_is_sent_back_once(conflicts, tmp_path: Path) -> None:
    """A unit whose dependencies merged long ago is named by no later merge, so
    no restack reaches it however far the trunk moves. Becoming unmergeable is
    the signal - and only becoming: a conflict still there on the next poll is
    not news, and re-dispatching it would rework the unit every five minutes."""
    conflicting = pr(mergeable=False)
    instance, seen = conflicts([[pr(mergeable=True)], [conflicting], [conflicting]])
    instance.poll()

    instance.poll()
    instance.poll()

    assert len(seen) == 1
    action, number, reason = seen[0]
    assert (action, number) == ("rework", 4)
    assert "conflict" in reason.lower()
    assert PrState.load(tmp_path / "poll.json")["4"]["mergeable"] is False


def test_an_undetermined_answer_is_not_a_conflict(conflicts, tmp_path: Path) -> None:
    """The host is undetermined for a while after every push, the pipeline's
    own included. Read as a conflict, it would rework nearly every unit right
    after pushing a good branch."""
    instance, seen = conflicts([[pr(mergeable=True)], [pr()]])
    instance.poll()

    instance.poll()

    assert seen == []
    assert PrState.load(tmp_path / "poll.json")["4"]["mergeable"] is True


def test_undetermined_then_mergeable_leaves_the_unit_alone(conflicts, tmp_path: Path) -> None:
    instance, seen = conflicts([[pr(mergeable=True)], [pr()], [pr(mergeable=True)]])
    instance.poll()

    instance.poll()
    instance.poll()

    assert seen == []
    assert PrState.load(tmp_path / "poll.json")["4"]["mergeable"] is True


def test_undetermined_then_conflicting_is_sent_back_once(conflicts) -> None:
    """Undetermined is asked again next poll, so the conflict it resolves into
    is still a transition - and still only one."""
    conflicting = pr(mergeable=False)
    instance, seen = conflicts([[pr(mergeable=True)], [pr()], [conflicting], [conflicting]])
    instance.poll()

    for _ in range(3):
        instance.poll()

    assert [(action, number) for action, number, _ in seen] == [("rework", 4)]
    assert "conflict" in seen[0][2].lower()


def test_a_conflict_the_host_forgets_for_a_poll_is_not_sent_back_again(conflicts) -> None:
    """The host goes undetermined whenever the base moves. Recorded as it
    stands, the conflict it resolves back into would look new, and a
    conflicted unit would be reworked once per merge into its base."""
    conflicting = pr(mergeable=False)
    instance, seen = conflicts([[pr(mergeable=True)], [conflicting], [pr()], [conflicting]])
    instance.poll()

    for _ in range(3):
        instance.poll()

    assert len(seen) == 1


def test_a_pull_request_conflicted_on_first_sight_is_sent_back(conflicts) -> None:
    """The trunk moves during a long build, and the pipeline opens the PR
    itself, so the first poll to meet it may already find it conflicting."""
    instance, seen = conflicts([[pr(9, head="spec/other/1")], [pr(mergeable=False)]])
    instance.poll()

    instance.poll()

    assert [(action, number) for action, number, _ in seen] == [("rework", 4)]


def test_a_pull_request_undetermined_on_first_sight_waits(conflicts) -> None:
    instance, seen = conflicts([[pr(9, head="spec/other/1")], [pr()]])
    instance.poll()

    instance.poll()

    assert seen == []


def test_the_conflicted_pull_requests_are_named_from_the_last_poll(tmp_path: Path) -> None:
    path = state_path(tmp_path, "app")
    assert unmergeable(path) == set(), "no poll yet"
    Poller(
        repo="app",
        state_path=path,
        list_prs=lambda: [pr(4, mergeable=False), pr(5, mergeable=True), pr(6)],
        dispatch=lambda *a, **k: None,
    ).poll()

    assert unmergeable(path) == {4}


# --- a failed poll is said, not swallowed ----------------------------------------------


def test_a_failed_poll_is_logged_and_leaves_the_recorded_state_alone(tmp_path: Path) -> None:
    """A forge client missing from a timer's PATH failed every tick for hours,
    and the only trace was a snapshot that stopped changing."""
    said: list[str] = []

    def broken() -> list[PullRequest]:
        raise FileNotFoundError(2, "No such file or directory", "az")

    state = tmp_path / "poll.json"
    instance = Poller(
        repo="app",
        state_path=state,
        list_prs=broken,
        dispatch=lambda *a, **k: None,
        log=said.append,
    )

    instance.poll()

    assert len(said) == 1
    assert "app" in said[0] and "FileNotFoundError" in said[0] and "az" in said[0]
    assert not state.exists(), "nothing recorded from a poll that did not happen"
