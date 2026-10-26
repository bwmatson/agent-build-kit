# test-kind-names-are-accepted-both-ways

The first change of the risk-tiered review work (design: `docs/risk-tiered-review-design.md`, philosophy:
`docs/agent-efficient-coding-philosophy.md`, both in the framework repo). It adds the type for the two kinds of test, `unit-test` and
`e2e-test`, and makes every place that reads a test kind outside the code accept either spelling, the old `tier1` and `tier2` or the
new, with a notice for the old. Nothing is renamed yet: the rename follows in `test-kinds-are-unit-test-and-e2e-test`, and work that
has not started yet is made to wait for this layer, so it is built on top of it.

The steps a person runs after each change of this work, and when, are in `docs/runbooks/migrate-to-risk-tiered-review.md` in the planning repo.
