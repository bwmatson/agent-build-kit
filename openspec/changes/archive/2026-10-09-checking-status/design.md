# Design

## The model

`PullRequest.checks` is a tuple of `Check(name, status, url)` with `CheckStatus` a closed set:
`passed`, `failed`, `cancelled`, `pending`. The old failing and cancelled name lists are removed in
the same change, so the two forms never coexist: their readers (the poller's snapshot and diffing, the
rework paths, the cancelled re-run, the host forges) use three helpers that return the failing names,
the cancelled names and the overall result.

The overall result is derived from the list: `failed` when any check failed, otherwise `pending` when
any is pending, otherwise `passed`; an empty list is `none`. Cancelled checks keep their own handling
(neither a pass nor a verdict); a list with only cancelled checks reads as pending for display, as
the re-run path expects. An unknown host value maps to `pending`, never `failed`, so it cannot send a
unit back.

## Mapping, per host

| Status | GitHub | Azure DevOps status | Azure DevOps build policy |
|---|---|---|---|
| passed | success, neutral, skipped | succeeded (not applicable is omitted) | approved (not applicable is omitted) |
| failed | failure, timed out | failed, error | rejected or broken, the build not cancelled |
| cancelled | cancelled | — | rejected with the build's result cancelled |
| pending | no conclusion (queued, in progress, waiting, requested) or unknown | pending, not set | queued, running |

Azure DevOps has two sources, merged into one list: pull request statuses, where several postings per
context are possible and the latest wins, and the build-validation policy's evaluations, where telling
a cancelled build from a failed one costs a call to the build. GitHub reads the newest commit's check
rollup. Each forge keeps its mapping beside its existing failing and cancelled sets, with a recorded
answer for every row. A check's link is the details URL on GitHub and the status's target or the
build's link on Azure DevOps, and is empty where the host gives none.

## No checks yet

Just after a push there may be no checks because CI has not registered, and a repo without CI has none
ever. The display rule: a pull request is `checking` while any check is pending, or while it has none
within a short window of its last push (`limits.checks_register_seconds`, default 120), and is
`in_review` once its checks have passed or the window has ended with none. The pipeline's own commit
status is a check and passes at the time it is posted.

## Where the inputs come from

A derived status needs two facts that `effective_state(unit, units)` cannot reach, since it sees only the units. The check
statuses are in the poller's snapshot for the repo (`prs-<repo>.json`), which holds each pull request's checks as name to status
and no link today; the link, which the list carries, is kept in the snapshot too. The time of the last push is not recorded: the
unit holds the pushed SHA (`StoredUnit.pushed`), and the only times on it are those of its history entries. So the unit gets a
`pushed_at`, written in the same update as `pushed`, subject to the unit store's rules for a field a newer or older release
does not know. The derivation takes both as inputs: a lookup of a pull request's checks, read from the snapshot by the callers
that show a status, and the unit's `pushed_at`. A caller with no lookup reads `in_review`, as it does today.

The callers are the status command (`cmd_status`, which lists a unit as "awaiting review" today and would list a checking one
separately), the graph page, the state label, and the unit summaries and counts in `serve/` (`server.py`, `metrics.py`), each of
which asks `effective_state`. Each of those decides whether to show the derived name or the stored state, as in
`dependents-follow-their-parent`.

A label and a draft follow a unit when its stored state changes, and a labelled pull request is refreshed on no other event
(`cli/pipeline.py`'s store hooks), so a unit would keep `in_review` on its pull request after its checks began. The poll that
records a pull request's checks also refreshes the label of a unit in review when the status it now derives differs from the
label the pull request carries, and does the same for a draft only where the stored state would have.

## Not a gate

`checking` is derived from a stored `in_review` unit and counts as in review for scheduling, queue
places and dependents. A failing check sends the unit back for rework as it does today.

## Snapshot

The poller's per-pull-request snapshot stores the list of checks with their statuses. A snapshot with the
old keys is recorded afresh on the next poll, as a first sighting is, so no migration is needed.
