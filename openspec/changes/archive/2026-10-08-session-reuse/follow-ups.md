## From `session-reuse/1`

- For group 4: when a build node ends without `_ended` (a killed call) but `state.session_id` is set, the reuse resolution step must either treat the recorded session as stale or record `state.session_id` with the runtime and model of the killed call. This is optional point 1.3 from the earlier round, which the builder deferred to group 4 with a sound reason.

## From `session-reuse/3`

- docs/unit-graph.md and CHANGELOG.md: say that the `adapt` accounting rounds continue the port's session only when build reuse is on. With reuse off, they start a new session, and the port's session is still the one recorded.
- docs/unit-graph.md:496 — The new sentence says the `adapt` follow-up rounds continue the port's session, with no condition. The CHANGELOG line "The accounting rounds of `adapt` continue the session the port ran in" says the same. Both hold only when build reuse is on. With reuse off, a follow-up starts a new session, and only the recorded build session stays the port's. Both paths are tested in test_session_continuation.py.

## From `session-reuse/4`

- src/agent_build_kit/runtimes/acp.py:1406-1407: if a resumed session gets a `usage_update` during `session/resume` but none during the prompt, `cost_usd` is reset to None and the call records no cost, not zero. That is safe, because it never over-counts. But such a call shows as `usage_source: none` when its spend is known to be zero. Consider recording 0.0 when there is a baseline and no later update, if that distinction matters to the reports.
