## From `replies-kept-until-posted/1`

- tests/cli/test_retry_replies.py: assert that the thread is still at AWAIT_REVIEW after `set_pending_replies`. Better, add a graph test that pauses a thread at a real `await_review` interrupt, rewrites its owed replies, and checks that a later REWORK delivery still resumes it.
- cli/pipeline.py `retry_replies`: take the lock on `branch_name(unit)` rather than `unit.branch`, so it uses the same lock file as the graph's run and delivery (graph/unit.py:199).
- tests/cli/test_retry_replies.py:71 — The retry tests check `pending_replies` after `set_pending_replies`, but not where the thread stands afterwards. Nothing shows that a thread re-written as `open_pr` is still waiting at `await_review` and still takes a review event.
- src/agent_build_kit/cli/pipeline.py:261 — `retry_replies` locks `unit.branch`, but the graph's run and delivery lock `branch_name(unit)` (graph/unit.py:199).
