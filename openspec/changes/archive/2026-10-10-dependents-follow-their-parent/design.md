# Design

## When a branch is changing

A predecessor's branch is changing when the predecessor is not in review, merged or satisfied and
any of these holds:

1. the branch head differs from the unit's last pushed head, because a rework or an interrupted
   rework has committed locally;
2. the unit is `rebasing`: its history is being rewritten before the new head exists;
3. the unit is itself `planned` with the cause `upstream_went_back` or `base_changed`, waiting on
   an upstream that is changing, so a grandchild follows when a grandparent changes.

A predecessor that is reworking with an unchanged head, or failed or held with an unchanged head
(an authentication failure that stopped it before any edit), is not changing: its dependents stay in
review. A failed or held predecessor with local commits is changing. The build-time check that a unit
about to push has a complete parent is unchanged; it asks whether the parent is in review at all, and
this asks whether the parent's branch is moving.

## The pass

After each poll and refresh, in the tick and in each round of a pass, every unit in review is
tested against this predicate over its same-repo predecessors, walking dependents to a fixed point so
a chain moves in one pass. The pass runs in `run_round` after `_refresh`, beside `gate_sent_back` and
`release_gated`, and the check sits beside `build_upstream_incomplete`, which asks the build-time
question over the same predecessors. A unit that qualifies takes its branch claim (a busy branch is
left for the next pass) and is re-read.

The unit's thread is not left alone. An in-review unit's thread waits at `await_review`, and only a
`ResumeEvent` moves it; every event kind today puts the unit in `running`, `held` or `in_review`, and none
parks it `planned`. So the move is a new event kind (for example `upstream_changed`), delivered to the
thread like the others, whose handler sets the unit to `planned` with the cause `upstream_went_back` and a
note naming the predecessor and why, keeps the approval, the branch and the pull request, and leaves the
thread where it is for the release to resume. Not storing the state without the event would leave a
thread that believes it is still in review. The head is read from the branch ref with git, injectable
for tests. A merged or satisfied predecessor never qualifies, so this does not compete with the
retargeting and restack done when a predecessor merges; a unit with a deferred restack or a held base
is skipped.

## Release

Unchanged: when the predecessor is back in review or merged the scheduler releases the unit, its
resume restacks onto the predecessor's new head, and a clean restack keeps the approval. An unchanged
head has nothing to restack.

## Drafts

The draft follower acts on `planned` as well as `running`: a unit with an open pull request that is
not in review is a draft; a unit in review is ready. A host without drafts, a closed pull request or
a failed call is skipped, as now.

## Display statuses

The vocabulary derives, for a stored `running` unit: `rebasing` when the last event is a conflict or
a moved base (feedback from a conflict, or the cause base changed, restack conflict or restack
deferred); `reworking` when the feedback is a review comment or a failing check; `running` otherwise.
They are derived, not stored, so there is no migration. `rebasing` is also an input to the predicate
above; `reworking` and `running` are not.

Group 1 is merged, and derived names reach consumers it did not touch, which compare or count by the
plain state. They are corrected here, in group 3: `serve/chat.py` `running()` asks whether
`effective_state(...) == "running"`, so a unit that is reworking or rebasing reads as not running and the
chat treats its worktree as idle; `serve/server.py` puts `effective_state` in the unit summary's `state`,
which the web pages read as the stored state; and `serve/metrics.py` counts the `abk.units` gauge by
`effective_state`, so `running` splits into three series. Each asks the stored state (a stored `running`
for the first; the stored state in `state` with the derived name beside it for the second; the stored state
for the third, so the gauge keeps one series per stored state) and the display surfaces keep the derived one.

## Accepted cost

A predecessor that commits a rework moves its dependents out of review and back, which toggles
their pull requests between draft and ready, and a restack that is not clean costs the dependent a
checks run and a review round. Only a rework that commits does this; a rework that only replies does
not. A grace period before pausing was considered and left out for simplicity.

Alternatives not taken: act only on predecessors that are failed, held, closed or planned; act on any
predecessor not in review (the build-time check's rule), which pauses dependents for replies-only reworks.
