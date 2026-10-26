## From `dependents-follow-their-parent/1`

- tests/pipeline/test_running_statuses.py: test_a_review_comment_during_a_rebase_reads_reworking stops at the REWORK `running` entry. It does not add the cause-less `running` entry that `prepare` writes next (graph/nodes.py:727), so it does not use the full graph shape that as_the_graph_records builds. Add `store.set_state(UID, RUNNING)` after the rework entry, so the test pins that prepare's entry does not hide the rework cause.
- Carried over from 1.3, which the builder declined because an existing label test contradicts it: once an inner review round clears feedback_source, a unit still answering a review comment reads `running`, not `reworking`. The unit that owns feedback-source lifetime should decide whether to keep the source through inner rounds.

## From `dependents-follow-their-parent/2`

- Rename `branch_is_changing` (wiring.py) so the name says it returns a reason string, for example `why_branch_is_changing`.
- docs/unit-graph.md: a unit with a deferred restack or a restack conflict is skipped while that cause stands, not 'left for a later pass'. Only a busy branch is left for the next pass.
- Group 3 must deliver the park as an event to the thread at `await_review`. Today `follow_predecessors` writes `planned` to the store only, so the release starts a fresh run instead of resuming the thread.
- src/agent_build_kit/pipeline/wiring.py:1792 — `branch_is_changing` reads as a yes/no check but returns the reason as a string, with an empty string meaning no.
- docs/unit-graph.md:619 — The doc says a unit with a deferred restack is 'left for a later pass', but `follow_predecessors` skips it on every pass for as long as its cause is `restack_deferred` or `restack_conflict`.
- src/agent_build_kit/pipeline/wiring.py:1861 — The move is written to the store only, and no event is delivered to the unit's thread, which is still waiting at `await_review`. The spec requires an event (task 3.1/3.4).
- src/agent_build_kit/pipeline/wiring.py:1846 — The `follow_predecessors` docstring breaks a line in the middle of a sentence ('Repeats until' / 'nothing moves').

## From `dependents-follow-their-parent/3`

- follow_predecessors (pipeline/wiring.py) logs and returns a unit as 'set back to planned' even when its thread declined the park (held, or no longer in review). Re-read the stored state after a delivery that returned True, and log only a real move. Track the units already attempted in a separate set so the pass still settles.
- The CHANGELOG bullet could say that the `depends_on`/`merge_gates` entries in the unit API now carry `status` rather than `state`.
- src/agent_build_kit/pipeline/wiring.py:2068 — When `deliver` returns True but the thread declines the park, the pass still logs and returns the unit as moved. The thread declines when the unit is held, or when the stored state is no longer `in_review`.
- CHANGELOG.md:8 — The bullet does not mention that the `depends_on` and `merge_gates` entries in the unit API now carry `status` instead of `state`.
