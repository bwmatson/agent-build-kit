"""Watching GitHub for the things that should wake the pipeline.

Webhooks would need a public endpoint, and nothing here is exposed, so the
runner polls (docs/architecture.md). On a single account there is
no approve/request-changes state either, so the signals are comments, labels,
merges, closures and check results.

The property that shapes the whole module: **only act on a change.** A poll
that re-dispatches what it saw last time would rework a unit every five
minutes, burning the usage window and force-pushing over itself.
"""

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.gh_poller import Poller, PrState, _snapshot


def pr(number: int = 4, **overrides) -> dict:
    defaults: dict = {
        "number": number,
        "headRefName": "spec/add-marker/1",
        "baseRefName": "main",
        "state": "OPEN",
        "isDraft": False,
        "mergedAt": None,
        "labels": [],
        "comments": [],
        "statusCheckRollup": [],
        "reviewDecision": "",
        "reviews": [],
    }
    return {**defaults, **overrides}


class FakeGh:
    def __init__(self, pages: list[list[dict]]) -> None:
        self.pages = pages
        self.calls = 0

    def __call__(self, args: list[str]) -> str:
        page = self.pages[min(self.calls, len(self.pages) - 1)]
        self.calls += 1
        return json.dumps(page)


@pytest.fixture
def poller(tmp_path: Path):
    def build(pages: list[list[dict]], **kw) -> tuple[Poller, list[tuple[str, int]]]:
        seen: list[tuple[str, int]] = []
        instance = Poller(
            repo="app",
            state_path=tmp_path / "poll.json",
            gh=FakeGh(pages),
            dispatch=lambda action, pr_number, **_: seen.append((action, pr_number)),
            **kw,
        )
        return instance, seen

    return build


def test_a_first_poll_records_state_without_dispatching_everything(poller) -> None:
    """Otherwise the first run after a restart reworks every open PR at once."""
    instance, seen = poller([[pr(), pr(5, headRefName="spec/add-marker/2")]])

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
            [pr(9, headRefName="fix/manual-thing")],
            [pr(9, headRefName="fix/manual-thing", comments=[{"id": "c1", "body": "hi"}])],
        ]
    )
    instance.poll()

    instance.poll()

    assert seen == []


def test_a_new_comment_asks_for_rework(poller) -> None:
    """With no request-changes state on a single account, a comment is how
    feedback arrives."""
    instance, seen = poller([[pr()], [pr(comments=[{"id": "c1", "body": "please rename this"}])]])
    instance.poll()

    instance.poll()

    assert ("rework", 4) in seen


def test_the_same_comment_twice_is_not_two_reworks(poller) -> None:
    commented = pr(comments=[{"id": "c1", "body": "please rename this"}])
    instance, seen = poller([[pr()], [commented], [commented]])
    instance.poll()
    instance.poll()

    instance.poll()

    assert len([event for event in seen if event[0] == "rework"]) == 1


def test_a_merge_moves_the_stack_along(poller) -> None:
    instance, seen = poller([[pr()], [pr(state="MERGED", mergedAt="2026-09-23T12:00:00Z")]])
    instance.poll()

    instance.poll()

    assert ("merged", 4) in seen


def test_a_closed_pr_stops_the_stack_rather_than_reworking_it(poller) -> None:
    """Closed without merging is a decision, not a defect: continuing would
    rebuild work that was deliberately dropped."""
    instance, seen = poller([[pr()], [pr(state="CLOSED")]])
    instance.poll()

    instance.poll()

    assert ("closed", 4) in seen
    assert not any(action == "rework" for action, _ in seen)


def test_a_failed_check_asks_for_rework(poller) -> None:
    instance, seen = poller(
        [
            [pr()],
            [pr(statusCheckRollup=[{"name": "CI", "conclusion": "FAILURE"}])],
        ]
    )
    instance.poll()

    instance.poll()

    assert ("rework", 4) in seen


def test_a_passing_check_is_not_an_event(poller) -> None:
    """Green is the expected state; dispatching on it would wake the pipeline
    for every successful run."""
    instance, seen = poller(
        [[pr()], [pr(statusCheckRollup=[{"name": "CI", "conclusion": "SUCCESS"}])]]
    )
    instance.poll()

    instance.poll()

    assert seen == []


def test_the_hold_label_stops_a_stack_advancing(poller) -> None:
    instance, seen = poller([[pr()], [pr(labels=[{"name": "agent:hold"}])]])
    instance.poll()

    instance.poll()

    assert ("hold", 4) in seen


def test_the_rework_label_is_feedback_given_elsewhere(poller) -> None:
    instance, seen = poller([[pr()], [pr(labels=[{"name": "agent:rework"}])]])
    instance.poll()

    instance.poll()

    assert ("rework", 4) in seen


def test_state_survives_a_restart(poller, tmp_path: Path) -> None:
    """Each tick is a new process; in-memory state would re-dispatch
    everything every five minutes."""
    commented = pr(comments=[{"id": "c1", "body": "hi"}])
    first, _ = poller([[pr()]])
    first.poll()

    second, seen = poller([[commented]])
    second.poll()
    third, seen_again = poller([[commented]])
    third.poll()

    assert ("rework", 4) in seen
    assert seen_again == []


def test_a_broken_response_does_not_lose_the_state(poller, tmp_path: Path) -> None:
    """A bad poll should cost one cycle, not re-dispatch history."""
    instance, seen = poller([[pr()]])
    instance.poll()

    broken = Poller(
        repo="app",
        state_path=tmp_path / "poll.json",
        gh=lambda args: "not json",
        dispatch=lambda action, pr_number, **_: seen.append((action, pr_number)),
    )
    broken.poll()

    assert seen == []
    assert PrState.load(tmp_path / "poll.json")["4"]["state"] == "OPEN"


def test_repeated_failures_back_off(poller, tmp_path: Path) -> None:
    """Hammering a failing endpoint every five minutes achieves nothing and
    looks like abuse from the other side."""
    failures = {"n": 0}

    def broken(args: list[str]) -> str:
        failures["n"] += 1
        raise RuntimeError("gh: could not connect")

    instance = Poller(
        repo="app",
        state_path=tmp_path / "poll.json",
        gh=broken,
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
        gh=lambda args: json.dumps([pr(1, mergedAt="2026-09-24T00:00:00Z")]),
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
        gh=lambda args: json.dumps(
            [pr(1, mergedAt="2026-09-24T00:00:00Z"), pr(2, mergedAt="2026-09-24T00:00:00Z")]
        ),
    ).poll()

    assert seen == []


def test_a_pr_created_and_merged_between_polls_is_not_lost(tmp_path: Path) -> None:
    """A PR opened after one poll and merged before the next would be
    recorded as merged without anyone being told, and since the poller only
    reports changes, no later poll would ever report it."""
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({"9": _snapshot(pr(9))}))
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, number)),
        gh=lambda args: json.dumps([pr(9), pr(14, mergedAt="2026-09-24T00:00:00Z")]),
    ).poll()

    assert ("merged", 14) in seen


def test_a_pr_first_seen_still_open_is_only_recorded(tmp_path: Path) -> None:
    """Nothing has happened to it yet. Only a terminal state is worth
    reporting for a PR we are meeting for the first time."""
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({"9": _snapshot(pr(9))}))
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, number)),
        gh=lambda args: json.dumps([pr(9), pr(14)]),
    ).poll()

    assert seen == []


def test_changes_requested_asks_for_rework(tmp_path: Path) -> None:
    """The strongest signal a reviewer can give, and `comments` alone misses
    it: a review leaving `reviewDecision: CHANGES_REQUESTED` and one inline
    comment is invisible to a poller reading `gh pr list --json comments`,
    which returns issue-level comments only."""
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({"16": _snapshot(pr(16))}))
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, k.get("reason", ""))),
        gh=lambda args: json.dumps([pr(16, reviewDecision="CHANGES_REQUESTED")]),
    ).poll()

    assert seen and seen[0][0] == "rework"
    assert "changes requested" in seen[0][1].lower()


def test_an_approval_is_not_rework(tmp_path: Path) -> None:
    """Approved is the opposite instruction. Reworking on it would rewrite a
    branch somebody just signed off."""
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({"16": _snapshot(pr(16))}))
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, k)),
        gh=lambda args: json.dumps([pr(16, reviewDecision="APPROVED")]),
    ).poll()

    assert seen == []


def test_changes_requested_only_fires_once(tmp_path: Path) -> None:
    """It stays CHANGES_REQUESTED until a new review supersedes it, so a poll
    every five minutes would otherwise rework the unit all night."""
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({"16": _snapshot(pr(16, reviewDecision="CHANGES_REQUESTED"))}))
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, k)),
        gh=lambda args: json.dumps([pr(16, reviewDecision="CHANGES_REQUESTED")]),
    ).poll()

    assert seen == []


def test_an_inline_review_comment_counts_as_a_comment(tmp_path: Path) -> None:
    """A reviewer commenting on a line is reviewing. Reading only issue-level
    comments meant an entire diff review registered as silence."""
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({"16": _snapshot(pr(16))}))
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, k.get("reason", ""))),
        gh=lambda args: json.dumps(
            [pr(16, reviews=[{"id": "r1", "state": "COMMENTED", "body": "this needs a look"}])]
        ),
    ).poll()

    assert seen and seen[0][0] == "rework"


def test_a_review_still_being_written_is_not_a_comment(tmp_path: Path) -> None:
    """A PENDING review is the reviewer's unsubmitted draft. GitHub shows it to
    its author — whose account the pipeline reads that repo as — and treating
    it as a comment sends the unit back for rework mid-review, with nothing
    to act on."""
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({"17": _snapshot(pr(17))}))
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, number)),
        gh=lambda args: json.dumps(
            [pr(17, reviews=[{"id": "r1", "state": "PENDING", "body": ""}])]
        ),
    ).poll()

    assert seen == []


def test_the_pipeline_s_own_replies_are_not_a_new_comment(tmp_path: Path) -> None:
    """Posting its answer to a review would otherwise send the unit straight
    back for rework, in response to itself."""
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({"17": _snapshot(pr(17))}))
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, number)),
        gh=lambda args: json.dumps(
            [pr(17, reviews=[{"id": "PRR_mine", "state": "COMMENTED", "body": ""}])]
        ),
        ignore=lambda number: {"PRR_mine"},
    ).poll()

    assert seen == []


def test_a_plain_comment_after_a_review_is_still_a_new_comment(tmp_path: Path) -> None:
    """Comments were compared by "the last id", taken from a list with every
    issue comment ahead of every review — so once a PR had a review, a later
    plain comment was never last, and a reviewer's follow-up went unseen."""
    review = {"id": "PRR_1", "state": "COMMENTED", "body": "a review"}
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({"17": _snapshot(pr(17, reviews=[review]))}))
    seen: list[tuple] = []

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, number)),
        gh=lambda args: json.dumps(
            [pr(17, reviews=[review], comments=[{"id": "IC_2", "body": "one more thing"}])]
        ),
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
        gh=lambda args: json.dumps([pr(16, reviewDecision="CHANGES_REQUESTED")]),
    ).poll()

    assert seen == [("rework", 16)], "a field absent from the old snapshot reads as unchanged"


def test_a_pr_first_seen_with_ci_already_red_is_reworked(tmp_path: Path) -> None:
    """The pipeline opens its own PRs, so CI usually finishes after the poll
    that first sees one. A failure recorded as the starting state is never
    newly failing, and the PR sits red while the tick builds on it."""
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({}))
    seen: list[tuple] = []
    failing = {"name": "config-check", "conclusion": "FAILURE"}

    Poller(
        repo="o/r",
        state_path=state,
        dispatch=lambda event, number, **k: seen.append((event, number, k.get("reason"))),
        gh=lambda args: json.dumps([pr(20, statusCheckRollup=[failing])]),
    ).poll()

    assert seen == [("rework", 20, "failing checks: config-check")]


def test_a_deferred_event_is_reported_again_until_it_is_handled(tmp_path: Path) -> None:
    """A handler defers an event for a unit still being built. Recording the
    change anyway would make that the only time it is ever seen."""
    held = pr(labels=[{"name": "agent:hold"}])
    pages = iter([[pr()], [held], [held], [held]])
    answers = iter([False, True])
    seen: list[str] = []

    def dispatch(event: str, number: int, **kwargs) -> bool:
        seen.append(event)
        return next(answers)

    instance = Poller(
        repo="o/r",
        state_path=tmp_path / "prs.json",
        gh=lambda args: json.dumps(next(pages)),
        dispatch=dispatch,
    )
    for _ in range(4):
        instance.poll()

    assert seen == ["hold", "hold"], "reported again once, then not after it was handled"


def test_a_deferred_event_on_a_pr_seen_for_the_first_time_is_kept(tmp_path: Path) -> None:
    state = tmp_path / "prs.json"
    state.write_text(json.dumps({}))
    merged = pr(20, mergedAt="2026-01-01T00:00:00Z", state="MERGED")
    answers = iter([False, True])
    seen: list[str] = []

    def dispatch(event: str, number: int, **kwargs) -> bool:
        seen.append(event)
        return next(answers)

    instance = Poller(
        repo="o/r", state_path=state, gh=lambda args: json.dumps([merged]), dispatch=dispatch
    )
    for _ in range(3):
        instance.poll()

    assert seen == ["merged", "merged"]
