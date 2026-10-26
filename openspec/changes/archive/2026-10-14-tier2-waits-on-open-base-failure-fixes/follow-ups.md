## From `tier2-waits-on-open-base-failure-fixes/1`

- Before a full tier 2 run, the gate calls `Tier2Session.scope` and then `run` calls it again, so the test-list diff is computed twice per run. The two calls could share one result. That would make the shared decision explicit and save a git call, but it is not needed for correctness.
- `tests/pipeline/test_tier2_gate_wiring.py` has no case for a profile that cannot select tests. The builder left it out because `tier2_runs_whole` now goes through the same `tier2_scope` call that main's scope tests cover. That reason holds, but adding the case would pin the whole-run answer at the runner level too.
