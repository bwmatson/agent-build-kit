## From `a-pr-that-stays-conflicting-is-moved-again/1`

- src/agent_build_kit/pipeline/pr_poller.py:284 — `fresh` is worked out before `_dispatch_changes` runs, and the conflict event goes out whenever that call did not defer. So one poll can send both a taken event (a `hold` from a newly added agent-hold label, or a comment/changes-requested/label `rework`) and a `conflict` for the same PR, judged on the unit's state from before the first event.
- src/agent_build_kit/pipeline/pr_poller.py:300 — `_fresh_conflict` calls `self.unit_of(number)` before it checks `mergeable`. In production that is `ui_review.unit_of`, which reads the whole store (`store.all()`), so every spec/ PR costs one full store read on every poll, mergeable or not.
- tests/pr_poller_fakes.py:1 — The module docstring ('successive pages of pull requests') and the PollerRig docstring ('Polls answered from `answers` in order (the last repeating)') describe the `FakePrs` helper in test_pr_poller.py. This rig has no `answers` list: each `poll(answer)` sets one answer and advances the fake clock.
- tests/pipeline/test_pr_poller_persistent_conflict.py:341 — `test_an_event_that_is_not_taken_is_offered_again_next_poll` would pass just as well with `rig.taken = True`. The poller ignores what the `conflict` dispatch returns, and re-offers it every poll whatever the answer, which is what the design intends.

## From `a-pr-that-stays-conflicting-is-moved-again/2`

- src/agent_build_kit/pipeline/events.py:1457 — When the unit is already queued or running in the lane, for example from a scan for an owed restack, `RestackLane.hand_over` silently drops the conflict `work`. on_conflict still logs 'handed to the restack lane'.

## From `a-pr-that-stays-conflicting-is-moved-again/3`

- Offering the unit's thread a `hold` before holding a conflicting unit under the claim (the part of 1.5 that was left out) needs its own thread-resume path and tests. Record it as a follow-up change.
