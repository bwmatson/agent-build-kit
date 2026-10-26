# test-kinds-are-unit-test-and-e2e-test

Phase 0 of the risk-tiered review work (design: `docs/risk-tiered-review-design.md` in the framework repo, philosophy:
`docs/agent-efficient-coding-philosophy.md`). The two kinds of test abk runs are called unit-test and e2e-test, and the word "tier" is
needed for how much review a change gets. This change renames them `unit-test` and `e2e-test` everywhere abk reads, writes or shows
them, internals included, and keeps the old names readable for one release.
