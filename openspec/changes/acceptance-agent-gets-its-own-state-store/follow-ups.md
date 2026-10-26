## From `acceptance-agent-gets-its-own-state-store/1`

- Task 1.14 (a live tier-2 run with the three verify.env entries set) has not been done, so the wiring has never run against a real agent. The PR description should say so. Things to confirm on the first live run: the ledger's first session record for the unit is the build step's own session; the worktree from `worktree_path(app, BRANCH, ABK_WORKTREE_ROOT)` is the cwd the agent listed it under; and in test_acp_build_unit the worktree still exists after the first tick.
- `assert_unit_session_listed` builds an `AcpRuntime` and sets `agent_command` on it after construction. If AcpRuntime gains a constructor argument or a named way to point it at a command, use that instead, so the test helper doesn't depend on a mutable attribute.
