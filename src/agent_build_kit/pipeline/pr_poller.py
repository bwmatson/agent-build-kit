"""Watching a repo's host for the things that should wake the pipeline.

Webhooks would need a publicly reachable endpoint and nothing here is exposed,
so this polls instead (docs/architecture.md). The signals are comments,
labels, merges, closures and check results — everything a `forges.PullRequest`
carries. Which host answers is the forge's business: this module reads only
that value, so a second host changes nothing below.

One property shapes everything below: **only act on a change.** A poll that
re-dispatched what it saw last time would rework the same unit every five
minutes — burning the usage window, force-pushing over itself, and drowning
the PR in comments. So each poll diffs against a recorded snapshot, and the
very first poll after a restart records without dispatching, rather than
treating every open PR as new.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Collection
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from agent_build_kit.config import active
from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline.units import CLOSED, MERGED

# Raises on failure, which is what drives the backoff below.
ListPrs = Callable[[], list[PullRequest]]
# Returning False defers the event: the change is kept, to be reported again.
Dispatch = Callable[..., bool | None]

# After this many consecutive failures, stop trying for a while: hammering a
# broken endpoint every five minutes achieves nothing and looks like abuse.
FAILURES_BEFORE_BACKOFF = 2
BACKOFF = timedelta(minutes=30)

HOLD_LABEL = "agent:hold"
REWORK_LABEL = "agent:rework"
# The `rework` reason for a branch that does not merge into its base.
# `events.on_rework` recognises it by this value.
CONFLICT_REASON = "merge conflict with its base"


def state_path(state_dir: Path, repo: str) -> Path:
    """Where a repo's poll snapshot lives."""
    return state_dir / f"prs-{repo}.json"


def unmergeable(path: Path) -> set[int]:
    """The PRs whose last definite answer, as the last poll recorded it, was
    that they do not merge into their base."""
    return {
        int(number) for number, seen in PrState.load(path).items() if seen.get("mergeable") is False
    }


class PrState:
    """The snapshot a poll compares against."""

    @staticmethod
    def load(path: Path) -> dict:
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return {}

    @staticmethod
    def save(path: Path, state: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2) + "\n")


def _comment_ids(pull: PullRequest, ignore: Collection[str] = ()) -> list[str]:
    """Every comment and submitted review on the PR, by id.

    `ignore` is what the pipeline posted itself (`pr_replies.own_posts`): its
    replies to a review are not a new review, and counting them would send the
    unit back for rework in response to its own answer.

    What counts as a comment at all is the forge's ruling — GitHub leaves out
    a review the reviewer has not submitted, Azure DevOps the notes its own
    server writes on every push — because a draft counted here would send the
    unit back for rework with nothing to act on.
    """
    return [i for i in pull.conversation if i not in ignore]


def snapshot(pull: PullRequest, ignore: Collection[str] = ()) -> dict:
    """What a poll records about `pull`, and what the next poll diffs against.

    Comment ids in `ignore` (the pipeline's own) are left out, so they never
    read as something new to act on.
    """
    ids = _comment_ids(pull, ignore)
    return {
        # `units` vocabulary, as `PullRequest.state` already is: merged,
        # closed, or open.
        "state": pull.state,
        # The newest of either kind. A reviewer commenting on a line is
        # reviewing, and reading only issue-level comments made a whole diff
        # review look like nothing happening.
        "last_comment": ids[-1] if ids else None,
        # The whole set, which is what "a new comment" is checked against.
        # `last_comment` alone is the last of a list with every issue comment
        # ahead of every review, so once a PR had a review, a later plain
        # comment was never "last" and went unseen. Kept for snapshots
        # recorded before this field existed.
        "comment_ids": sorted(ids),
        "review_decision": pull.review_decision,
        "labels": sorted(pull.labels),
        "failing_checks": sorted(pull.failing_checks),
        "head": pull.head,
        # True, False, or None while the host has not worked it out.
        "mergeable": pull.mergeable,
    }


def _migrate(before: dict) -> dict:
    """An older snapshot, in the words the GitHub API used to hand over.

    These files are machine-local and survive an upgrade, so a snapshot
    written before the forges existed has `merged: true` and `CHANGES_REQUESTED`
    where this one has a `units` state. Read as is, every in-flight PR would
    look changed on the first poll after the upgrade and be reworked once for
    nothing.
    """
    if "merged" not in before:
        return before
    return {
        **before,
        "state": MERGED
        if before.get("merged")
        else CLOSED
        if before.get("state") == "CLOSED"
        else "open",
        "review_decision": (
            "changes_requested" if before.get("review_decision") == "CHANGES_REQUESTED" else ""
        ),
    }


class Poller(BaseModel):
    """One repo's worth of watching.

    Mutable, unlike the values it produces: the backoff counters are the
    point, and they have to survive from one poll to the next.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    repo: str
    state_path: Path
    dispatch: Dispatch
    # Every PR in the repo, from its own host.
    list_prs: ListPrs
    # Comment and review ids the pipeline posted on a PR itself, by number.
    ignore: Callable[[int], set[str]] = lambda number: set()
    failures: int = 0
    quiet_until: datetime | None = None

    def poll(self) -> None:
        if self.quiet_until and datetime.now(UTC) < self.quiet_until:
            return

        try:
            pulls = self.list_prs()
        except Exception:
            # A bad poll costs one cycle. The recorded state is left untouched,
            # so nothing is re-dispatched when the endpoint recovers.
            self.failures += 1
            if self.failures >= FAILURES_BEFORE_BACKOFF:
                self.quiet_until = datetime.now(UTC) + BACKOFF
            return

        self.failures = 0
        self.quiet_until = None

        known = PrState.load(self.state_path)
        # "Have we ever looked", not "do we know of any PRs". The file's
        # existence is the signal: a repo whose first spec/ PR appears after
        # an empty poll was otherwise treated as fresh forever, and every
        # event on that PR swallowed.
        first_run = not self.state_path.exists()
        updated = dict(known)

        for pull in pulls:
            # Never touch a branch a human owns: the pipeline may only rework
            # and force-push its own. Checked here as well as by the forge:
            # this is the rule that keeps a force-push off someone's work.
            if not pull.head.startswith(active().github.branch_prefix):
                continue

            number = str(pull.number)
            current = snapshot(pull, self.ignore(int(number)))
            if current["mergeable"] is None and number in known:
                # The host resets its answer to undetermined whenever the base
                # moves and works it out lazily. Recorded, it would make the
                # conflict it resolves back into look new, and rework a
                # conflicted unit once per trunk merge. So the last definite
                # answer stands.
                current["mergeable"] = known[number].get("mergeable")
            updated[number] = current

            if first_run:
                # A fresh state file must not read as a hundred simultaneous
                # events, so the first poll of a repo only records.
                continue

            if number not in known:
                # Created since the last poll. Nothing has happened to it yet
                # unless it is already finished — a PR opened and merged
                # inside one interval would be recorded as merged with nobody
                # told, and since the poller reports only changes, no later
                # poll could ever report it.
                if self._dispatch_terminal(int(number), current, pull) is False:
                    del updated[number]
                continue

            if self._dispatch_changes(int(number), _migrate(known[number]), current, pull) is False:
                # Deferred: its unit is being built (see `events`). Recording
                # the new snapshot would make this the last time the change is
                # seen, so the old one stays and the next poll reports it again.
                updated[number] = known[number]

        PrState.save(self.state_path, updated)

    def _dispatch_terminal(self, number: int, current: dict, pull: PullRequest) -> bool | None:
        """Report a PR we are meeting for the first time if it is done — or if
        its CI is already red, or it already conflicts with its base.

        The pipeline opens its PRs itself, so CI usually finishes after the
        next poll has first seen the PR. A failure then was recorded as the
        PR's starting state and never reported: nothing afterwards was *newly*
        failing, and the PR sat red while the tick built on it. A conflict is
        the same: the trunk can move during a long build, and the host starts
        working out mergeability when the PR is created.
        """
        if current["state"] == MERGED:
            return self.dispatch("merged", number, pull=pull)
        if current["state"] == CLOSED:
            return self.dispatch("closed", number, pull=pull)
        if current["failing_checks"]:
            return self.dispatch(
                "rework",
                number,
                pull=pull,
                reason=f"failing checks: {', '.join(current['failing_checks'])}",
            )
        if current["mergeable"] is False:
            return self.dispatch("rework", number, pull=pull, reason=CONFLICT_REASON)
        return None

    def _dispatch_changes(
        self, number: int, before: dict, after: dict, pull: PullRequest
    ) -> bool | None:
        """`before` is read from disk, so it may predate a field `after` has.

        Every lookup into it therefore tolerates absence, reading a missing
        field as unchanged. Adding `review_decision` without this made every
        poll fail with KeyError against state recorded the day before.
        """
        if after["state"] == MERGED and before.get("state") != MERGED:
            return self.dispatch("merged", number, pull=pull)

        if after["state"] == CLOSED and before.get("state") != CLOSED:
            # Closed without merging is a decision, not a defect: continuing
            # would rebuild work that was deliberately dropped.
            return self.dispatch("closed", number, pull=pull)

        labels_added = set(after["labels"]) - set(before.get("labels") or [])
        if HOLD_LABEL in labels_added:
            return self.dispatch("hold", number, pull=pull)

        if REWORK_LABEL in labels_added:
            return self.dispatch("rework", number, pull=pull, reason="agent:rework label")

        # Before the comment check: a review carrying both a decision and a
        # note should report the decision, which is the actionable half.
        if after["review_decision"] == "changes_requested" and (
            before.get("review_decision") != "changes_requested"
        ):
            # Only on the transition. The decision stays as it is until a later
            # review supersedes it, so reporting it every poll would rework the
            # unit every five minutes all night.
            return self.dispatch("rework", number, pull=pull, reason="review: changes requested")

        if "comment_ids" in before:
            new_comment = bool(set(after["comment_ids"]) - set(before["comment_ids"]))
        else:
            new_comment = after["last_comment"] != before.get("last_comment")
        if new_comment:
            return self.dispatch("rework", number, pull=pull, reason="new comment")

        newly_failing = set(after["failing_checks"]) - set(before.get("failing_checks") or [])
        if newly_failing:
            # Only newly failing: a check that was already red is not news, and
            # green is the expected state rather than an event.
            return self.dispatch(
                "rework", number, pull=pull, reason=f"failing checks: {', '.join(newly_failing)}"
            )

        if after["mergeable"] is False and before.get("mergeable") is not False:
            # Only on becoming conflicting, like the checks above. Undetermined
            # is not a conflict: the host says it for a while after every push,
            # the pipeline's own included, and the next poll asks again.
            # `before` holds the last definite answer, so an undetermined one
            # between two conflicting answers is not a transition (see `poll`).
            return self.dispatch("rework", number, pull=pull, reason=CONFLICT_REASON)
        return None
