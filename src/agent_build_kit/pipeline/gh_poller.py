"""Watching GitHub for the things that should wake the pipeline.

Webhooks would need a publicly reachable endpoint and nothing here is exposed,
so this polls instead (docs/architecture.md). On a single GitHub
account there is no approve or request-changes state either, so the signals
are comments, labels, merges, closures and check results.

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
from agent_build_kit.pipeline.shell import gh_out

Gh = Callable[[list[str]], str]
# Returning False defers the event: the change is kept, to be reported again.
Dispatch = Callable[..., bool | None]

# `reviewDecision` and `reviews` are here because `comments` alone misses a
# normal GitHub review entirely: it returns issue-level comments only, so a
# reviewer who leaves inline notes on the diff and submits CHANGES_REQUESTED
# registers as silence: one inline comment, a CHANGES_REQUESTED decision, and
# `comments: []`.
FIELDS = (
    "number,headRefName,baseRefName,state,isDraft,mergedAt,labels,comments,"
    "statusCheckRollup,reviewDecision,reviews"
)

# After this many consecutive failures, stop trying for a while: hammering a
# broken endpoint every five minutes achieves nothing and looks like abuse.
FAILURES_BEFORE_BACKOFF = 2
BACKOFF = timedelta(minutes=30)

HOLD_LABEL = "agent:hold"
REWORK_LABEL = "agent:rework"


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


def _comment_ids(pull: dict, ignore: Collection[str] = ()) -> list[str]:
    """Every comment and submitted review on the PR, by id.

    `ignore` is what the pipeline posted itself (`pr_replies.own_posts`): its
    replies to a review are not a new review, and counting them would send
    the unit back for rework in response to its own answer.

    Not a PENDING review: that is a draft the reviewer has not submitted.
    GitHub shows it to its own author, and the repo is read as its owner — so
    a review still being written would count as a new comment and send the
    unit back for rework with nothing to act on.
    """
    ids = [str(item["id"]) for item in (pull.get("comments") or []) if item.get("id")]
    ids += [
        str(item["id"])
        for item in (pull.get("reviews") or [])
        if item.get("id") and item.get("state") != "PENDING"
    ]
    return [i for i in ids if i not in ignore]


def _snapshot(pull: dict, ignore: Collection[str] = ()) -> dict:
    checks = pull.get("statusCheckRollup") or []
    ids = _comment_ids(pull, ignore)
    return {
        "state": pull.get("state"),
        "merged": bool(pull.get("mergedAt")),
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
        "review_decision": pull.get("reviewDecision") or "",
        "labels": sorted(label.get("name", "") for label in pull.get("labels") or []),
        "failing_checks": sorted(
            check.get("name", "")
            for check in checks
            if str(check.get("conclusion", "")).upper() in ("FAILURE", "TIMED_OUT", "CANCELLED")
        ),
        "head": pull.get("headRefName"),
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
    # Raises on failure, which is what drives the backoff below.
    gh: Gh = gh_out
    # Comment and review ids the pipeline posted on a PR itself, by number.
    ignore: Callable[[int], set[str]] = lambda number: set()
    failures: int = 0
    quiet_until: datetime | None = None

    def _fetch(self) -> list[dict]:
        raw = self.gh(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                self.repo,
                "--state",
                "all",
                "--limit",
                "100",
                "--json",
                FIELDS,
            ]
        )
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("expected a list of pull requests")
        return data

    def poll(self) -> None:
        if self.quiet_until and datetime.now(UTC) < self.quiet_until:
            return

        try:
            pulls = self._fetch()
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
            head = pull.get("headRefName", "")
            # Never touch a branch a human owns: the pipeline may only rework
            # and force-push its own.
            if not head.startswith(active().github.branch_prefix):
                continue

            number = str(pull["number"])
            current = _snapshot(pull, self.ignore(int(number)))
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

            if self._dispatch_changes(int(number), known[number], current, pull) is False:
                # Deferred: its unit is being built (see `events`). Recording
                # the new snapshot would make this the last time the change is
                # seen, so the old one stays and the next poll reports it again.
                updated[number] = known[number]

        PrState.save(self.state_path, updated)

    def _dispatch_terminal(self, number: int, current: dict, pull: dict) -> bool | None:
        """Report a PR we are meeting for the first time if it is done — or if
        its CI is already red.

        The pipeline opens its PRs itself, so CI usually finishes after the
        next poll has first seen the PR. A failure then was recorded as the
        PR's starting state and never reported: nothing afterwards was *newly*
        failing, and the PR sat red while the tick built on it.
        """
        if current["merged"]:
            return self.dispatch("merged", number, pull=pull)
        if current["state"] == "CLOSED":
            return self.dispatch("closed", number, pull=pull)
        if current["failing_checks"]:
            return self.dispatch(
                "rework",
                number,
                pull=pull,
                reason=f"failing checks: {', '.join(current['failing_checks'])}",
            )
        return None

    def _dispatch_changes(self, number: int, before: dict, after: dict, pull: dict) -> bool | None:
        """`before` is read from disk, so it may predate a field `after` has.

        Every lookup into it therefore tolerates absence, reading a missing
        field as unchanged. Adding `review_decision` without this made every
        poll fail with KeyError against state recorded the day before.
        """
        if after["merged"] and not before.get("merged"):
            return self.dispatch("merged", number, pull=pull)

        if after["state"] == "CLOSED" and before.get("state") != "CLOSED":
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
        if after["review_decision"] == "CHANGES_REQUESTED" and (
            before.get("review_decision") != "CHANGES_REQUESTED"
        ):
            # Only on the transition. The decision stays CHANGES_REQUESTED until
            # a later review supersedes it, so reporting it every poll would
            # rework the unit every five minutes all night.
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
        return None
