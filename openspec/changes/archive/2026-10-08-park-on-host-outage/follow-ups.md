## From `park-on-host-outage/1`

- test_a_unit_with_replies_owed_and_new_feedback_is_reworked only asserts that rework ran. It could also assert that `claude:rework` comes before the pull-request step and that the owed reply is still posted afterwards. That would pin down the whole route: prepare goes to rework, then checks, then open_pr.
- Point 1.3 was declined because the builder cannot edit design.md. A person should decide whether `resume_thread` should handle a `HostUnavailable` during event delivery the way it handles `BranchBusy`: leave the unit in its state and keep the event for the next poll. If so, add it as a follow-up task on the change.
